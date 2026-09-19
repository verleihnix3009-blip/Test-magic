import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
DATA_DIR = BASE_DIR / "data"
DB_PATH = BASE_DIR / "game.db"

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8000"))

SESSIONS = {}


def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_database():
    connection = db()

    schema = (BASE_DIR / "schema.sql").read_text(encoding="utf-8")
    connection.executescript(schema)

    connection.commit()
    connection.close()


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_bytes(16)

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        120000
    )

    return salt.hex() + ":" + password_hash.hex()


def verify_password(password, stored):
    try:
        salt_hex, hash_hex = stored.split(":", 1)

        salt = bytes.fromhex(salt_hex)

        password_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            120000
        )

        return hmac.compare_digest(
            password_hash.hex(),
            hash_hex
        )
    except (ValueError, TypeError):
        return False


def send_json(handler, data, status=200):
    body = json.dumps(
        data,
        ensure_ascii=False
    ).encode("utf-8")

    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler):
    length = int(handler.headers.get("Content-Length", "0"))

    if length > 1024 * 1024:
        return None

    raw = handler.rfile.read(length)

    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def get_session(handler):
    cookie = handler.headers.get("Cookie", "")

    for part in cookie.split(";"):
        part = part.strip()

        if part.startswith("session="):
            token = part.split("=", 1)[1]
            return SESSIONS.get(token)

    return None


def create_session(account_id):
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = account_id
    return token


def set_session_cookie(handler, token):
    handler.send_header(
        "Set-Cookie",
        f"session={token}; HttpOnly; SameSite=Lax; Path=/"
    )


def load_json(filename):
    path = DATA_DIR / filename

    if not path.exists():
        return {}

    return json.loads(
        path.read_text(encoding="utf-8")
    )


def get_character(account_id):
    connection = db()

    character = connection.execute(
        """
        SELECT *
        FROM characters
        WHERE account_id = ?
        LIMIT 1
        """,
        (account_id,)
    ).fetchone()

    connection.close()

    return character


def character_state(account_id):
    connection = db()

    character = connection.execute(
        """
        SELECT *
        FROM characters
        WHERE account_id = ?
        LIMIT 1
        """,
        (account_id,)
    ).fetchone()

    if character is None:
        connection.close()
        return None

    inventory = connection.execute(
        """
        SELECT
            items.id,
            items.name,
            items.description,
            items.item_type,
            inventory.amount
        FROM inventory
        JOIN items ON items.id = inventory.item_id
        WHERE inventory.character_id = ?
        ORDER BY items.name
        """,
        (character["id"],)
    ).fetchall()

    quests = connection.execute(
        """
        SELECT
            quests.quest_key,
            quests.name,
            quests.description,
            quests.required_monster,
            quests.required_amount,
            quests.reward_experience,
            quests.reward_gold,
            character_quests.status,
            character_quests.progress
        FROM character_quests
        JOIN quests ON quests.id = character_quests.quest_id
        WHERE character_quests.character_id = ?
        ORDER BY quests.id
        """,
        (character["id"],)
    ).fetchall()

    connection.close()

    return {
        "character": dict(character),
        "inventory": [dict(item) for item in inventory],
        "quests": [dict(quest) for quest in quests]
    }


def add_experience(connection, character_id, amount):
    character = connection.execute(
        """
        SELECT level, experience
        FROM characters
        WHERE id = ?
        """,
        (character_id,)
    ).fetchone()

    if character is None:
        return False

    new_level = character["level"]
    new_experience = character["experience"] + amount

    while new_experience >= new_level * 100:
        new_experience -= new_level * 100
        new_level += 1

    connection.execute(
        """
        UPDATE characters
        SET level = ?,
            experience = ?
        WHERE id = ?
        """,
        (
            new_level,
            new_experience,
            character_id
        )
    )

    return True


def update_quest_progress(
    connection,
    character_id,
    monster_name
):
    rows = connection.execute(
        """
        SELECT
            character_quests.quest_id,
            character_quests.progress,
            quests.required_monster,
            quests.required_amount
        FROM character_quests
        JOIN quests ON quests.id = character_quests.quest_id
        WHERE character_quests.character_id = ?
          AND character_quests.status = 'angenommen'
        """,
        (character_id,)
    ).fetchall()

    completed = []

    for quest in rows:
        if quest["required_monster"] != monster_name:
            continue

        progress = min(
            quest["progress"] + 1,
            quest["required_amount"]
        )

        status = (
            "bereit"
            if progress >= quest["required_amount"]
            else "angenommen"
        )

        connection.execute(
            """
            UPDATE character_quests
            SET progress = ?,
                status = ?
            WHERE character_id = ?
              AND quest_id = ?
            """,
            (
                progress,
                status,
                character_id,
                quest["quest_id"]
            )
        )

        if status == "bereit":
            completed.append(quest["quest_id"])

    return completed


class GameHandler(BaseHTTPRequestHandler):

    def log_message(self, format_string, *args):
        print(
            "%s - %s"
            % (
                self.address_string(),
                format_string % args
            )
        )

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            return self.serve_file(
                WEB_DIR / "index.html",
                "text/html; charset=utf-8"
            )

        if path.startswith("/web/"):
            filename = path.removeprefix("/web/")

            if ".." in filename:
                return send_json(
                    self,
                    {"error": "Ungültiger Dateiname."},
                    400
                )

            file_path = WEB_DIR / filename

            if file_path.is_file():
                content_type = "text/plain; charset=utf-8"

                if filename.endswith(".css"):
                    content_type = "text/css; charset=utf-8"

                elif filename.endswith(".js"):
                    content_type = "application/javascript; charset=utf-8"

                elif filename.endswith(".html"):
                    content_type = "text/html; charset=utf-8"

                return self.serve_file(
                    file_path,
                    content_type
                )

        if path == "/api/state":
            account_id = get_session(self)

            if not account_id:
                return send_json(
                    self,
                    {
                        "logged_in": False
                    }
                )

            state = character_state(account_id)

            return send_json(
                self,
                {
                    "logged_in": True,
                    "state": state
                }
            )

        return send_json(
            self,
            {
                "error": "Seite nicht gefunden."
            },
            404
        )

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        data = read_json(self)

        if data is None:
            return send_json(
                self,
                {
                    "error": "Ungültige Anfrage."
                },
                400
            )

        if path == "/api/register":
            return self.register(data)

        if path == "/api/login":
            return self.login(data)

        if path == "/api/logout":
            return self.logout()

        if path == "/api/move":
            return self.move(data)

        if path == "/api/battle":
            return self.battle(data)

        if path == "/api/quest/accept":
            return self.accept_quest(data)

        if path == "/api/quest/complete":
            return self.complete_quest(data)

        if path == "/api/item/use":
            return self.use_item(data)

        return send_json(
            self,
            {
                "error": "API-Endpunkt nicht gefunden."
            },
            404
        )

    def serve_file(self, path, content_type):
        try:
            body = path.read_bytes()
        except FileNotFoundError:
            return send_json(
                self,
                {
                    "error": "Datei nicht gefunden."
                },
                404
            )

        self.send_response(200)
        self.send_header(
            "Content-Type",
            content_type
        )
        self.send_header(
            "Content-Length",
            str(len(body))
        )
        self.end_headers()
        self.wfile.write(body)

    def register(self, data):
        username = str(
            data.get("username", "")
        ).strip()

        password = str(
            data.get("password", "")
        )

        character_name = str(
            data.get("character_name", "")
        ).strip()

        if len(username) < 3:
            return send_json(
                self,
                {
                    "error":
                    "Der Benutzername muss mindestens 3 Zeichen lang sein."
                },
                400
            )

        if len(password) < 6:
            return send_json(
                self,
                {
                    "error":
                    "Das Passwort muss mindestens 6 Zeichen lang sein."
                },
                400
            )

        if not character_name:
            return send_json(
                self,
                {
                    "error":
                    "Bitte gib einen Charakternamen ein."
                },
                400
            )

        connection = db()

        try:
            cursor = connection.execute(
                """
                INSERT INTO accounts
                    (username, password_hash)
                VALUES
                    (?, ?)
                """,
                (
                    username,
                    hash_password(password)
                )
            )

            account_id = cursor.lastrowid

            character_cursor = connection.execute(
                """
                INSERT INTO characters
                    (account_id, name)
                VALUES
                    (?, ?)
                """,
                (
                    account_id,
                    character_name
                )
            )

            character_id = character_cursor.lastrowid

            quest = connection.execute(
                """
                SELECT id
                FROM quests
                WHERE quest_key = 'erster_waldkobold'
                """
            ).fetchone()

            if quest:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO character_quests
                        (character_id, quest_id)
                    VALUES
                        (?, ?)
                    """,
                    (
                        character_id,
                        quest["id"]
                    )
                )

            heal_potion = connection.execute(
                """
                SELECT id
                FROM items
                WHERE name = 'Heiltrank'
                """
            ).fetchone()

            if heal_potion:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO inventory
                        (character_id, item_id, amount)
                    VALUES
                        (?, ?, 2)
                    """,
                    (
                        character_id,
                        heal_potion["id"]
                    )
                )

            connection.commit()

            token = create_session(account_id)

            self.send_response(200)
            set_session_cookie(self, token)

            body = json.dumps(
                {
                    "success": True,
                    "message":
                    "Dein Charakter wurde erstellt."
                },
                ensure_ascii=False
            ).encode("utf-8")

            self.send_header(
                "Content-Type",
                "application/json; charset=utf-8"
            )
            self.send_header(
                "Content-Length",
                str(len(body))
            )
            self.end_headers()
            self.wfile.write(body)

        except sqlite3.IntegrityError:
            connection.rollback()

            send_json(
                self,
                {
                    "error":
                    "Benutzername oder Charaktername ist bereits vergeben."
                },
                409
            )

        finally:
            connection.close()

    def login(self, data):
        username = str(
            data.get("username", "")
        ).strip()

        password = str(
            data.get("password", "")
        )

        connection = db()

        account = connection.execute(
            """
            SELECT *
            FROM accounts
            WHERE username = ?
            """,
            (username,)
        ).fetchone()

        connection.close()

        if (
            account is None
            or not verify_password(
                password,
                account["password_hash"]
            )
        ):
            return send_json(
                self,
                {
                    "error":
                    "Benutzername oder Passwort ist falsch."
                },
                401
            )

        token = create_session(
            account["id"]
        )

        self.send_response(200)
        set_session_cookie(self, token)

        body = json.dumps(
            {
                "success": True,
                "message":
                "Anmeldung erfolgreich."
            },
            ensure_ascii=False
        ).encode("utf-8")

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )
        self.send_header(
            "Content-Length",
            str(len(body))
        )
        self.end_headers()
        self.wfile.write(body)

    def logout(self):
        cookie = self.headers.get("Cookie", "")

        token_to_remove = None

        for part in cookie.split(";"):
            part = part.strip()

            if part.startswith("session="):
                token_to_remove = part.split("=", 1)[1]

        if token_to_remove:
            SESSIONS.pop(
                token_to_remove,
                None
            )

        return send_json(
            self,
            {
                "success": True
            }
        )

    def move(self, data):
        account_id = get_session(self)

        if not account_id:
            return send_json(
                self,
                {
                    "error":
                    "Du bist nicht angemeldet."
                },
                401
            )

        direction = str(
            data.get("direction", "")
        )

        directions = {
            "up": (0, -1),
            "down": (0, 1),
            "left": (-1, 0),
            "right": (1, 0)
        }

        if direction not in directions:
            return send_json(
                self,
                {
                    "error":
                    "Ungültige Bewegungsrichtung."
                },
                400
            )

        dx, dy = directions[direction]

        connection = db()

        character = connection.execute(
            """
            SELECT *
            FROM characters
            WHERE account_id = ?
            """,
            (account_id,)
        ).fetchone()

        if character is None:
            connection.close()

            return send_json(
                self,
                {
                    "error":
                    "Charakter nicht gefunden."
                },
                404
            )

        new_x = max(
            0,
            min(20, character["x"] + dx)
        )

        new_y = max(
            0,
            min(20, character["y"] + dy)
        )

        connection.execute(
            """
            UPDATE characters
            SET x = ?,
                y = ?
            WHERE id = ?
            """,
            (
                new_x,
                new_y,
                character["id"]
            )
        )

        connection.commit()
        connection.close()

        return send_json(
            self,
            {
                "success": True,
                "x": new_x,
                "y": new_y
            }
        )

    def battle(self, data):
        account_id = get_session(self)

        if not account_id:
            return send_json(
                self,
                {
                    "error":
                    "Du bist nicht angemeldet."
                },
                401
            )

        monster_id = str(
            data.get(
                "monster_id",
                "waldkobold"
            )
        )

        monsters = load_json(
            "monsters.json"
        ).get("monsters", [])

        monster = next(
            (
                item
                for item in monsters
                if item["id"] == monster_id
            ),
            None
        )

        if monster is None:
            return send_json(
                self,
                {
                    "error":
                    "Monster nicht gefunden."
                },
                404
            )

        connection = db()

        character = connection.execute(
            """
            SELECT *
            FROM characters
            WHERE account_id = ?
            """,
            (account_id,)
        ).fetchone()

        if character is None:
            connection.close()

            return send_json(
                self,
                {
                    "error":
                    "Charakter nicht gefunden."
                },
                404
            )

        player_damage = max(
            1,
            10 + character["level"] * 2
        )

        monster_damage = max(
            1,
            monster["attack"] - character["level"]
        )

        player_hp = character["hp"]

        monster_hp = monster["hp"]

        log = []

        while (
            player_hp > 0
            and monster_hp > 0
        ):
            monster_hp -= player_damage

            log.append(
                f"Du verursachst {player_damage} Schaden."
            )

            if monster_hp <= 0:
                break

            player_hp -= monster_damage

            log.append(
                f"Der {monster['name']} verursacht "
                f"{monster_damage} Schaden."
            )

        if player_hp <= 0:
            player_hp = 1

            connection.execute(
                """
                UPDATE characters
                SET hp = ?
                WHERE id = ?
                """,
                (
                    player_hp,
                    character["id"]
                )
            )

            connection.commit()
            connection.close()

            return send_json(
                self,
                {
                    "success": False,
                    "message":
                    "Du wurdest besiegt. Du kannst mit 1 Lebenspunkt weiterkämpfen.",
                    "log": log
                }
            )

        reward_gold = (
            monster["gold_min"]
            + (
                monster["gold_max"]
                - monster["gold_min"]
            ) // 2
        )

        connection.execute(
            """
            UPDATE characters
            SET hp = ?,
                gold = gold + ?
            WHERE id = ?
            """,
            (
                player_hp,
                reward_gold,
                character["id"]
            )
        )

        add_experience(
            connection,
            character["id"],
            monster["experience"]
        )

        completed = update_quest_progress(
            connection,
            character["id"],
            monster["name"]
        )

        connection.commit()
        connection.close()

        return send_json(
            self,
            {
                "success": True,
                "message":
                f"Du hast den {monster['name']} besiegt.",
                "experience":
                monster["experience"],
                "gold":
                reward_gold,
                "quest_ready":
                len(completed) > 0,
                "log":
                log
            }
        )

    def accept_quest(self, data):
        account_id = get_session(self)

        if not account_id:
            return send_json(
                self,
                {
                    "error":
                    "Du bist nicht angemeldet."
                },
                401
            )

        quest_key = str(
            data.get("quest_key", "")
        )

        connection = db()

        character = get_character(account_id)

        if character is None:
            connection.close()

            return send_json(
                self,
                {
                    "error":
                    "Charakter nicht gefunden."
                },
                404
            )

        quest = connection.execute(
            """
            SELECT *
            FROM quests
            WHERE quest_key = ?
            """,
            (quest_key,)
        ).fetchone()

        if quest is None:
            connection.close()

            return send_json(
                self,
                {
                    "error":
                    "Quest nicht gefunden."
                },
                404
            )

        connection.execute(
            """
            INSERT OR IGNORE INTO character_quests
                (character_id, quest_id)
            VALUES
                (?, ?)
            """,
            (
                character["id"],
                quest["id"]
            )
        )

        connection.commit()
        connection.close()

        return send_json(
            self,
            {
                "success": True,
                "message":
                "Quest angenommen."
            }
        )

    def complete_quest(self, data):
        account_id = get_session(self)

        if not account_id:
            return send_json(
                self,
                {
                    "error":
                    "Du bist nicht angemeldet."
                },
                401
            )

        quest_key = str(
            data.get("quest_key", "")
        )

        connection = db()

        character = get_character(account_id)

        if character is None:
            connection.close()

            return send_json(
                self,
                {
                    "error":
                    "Charakter nicht gefunden."
                },
                404
            )

        quest = connection.execute(
            """
            SELECT
                quests.*,
                character_quests.status,
                character_quests.progress
            FROM character_quests
            JOIN quests
                ON quests.id = character_quests.quest_id
            WHERE character_quests.character_id = ?
              AND quests.quest_key = ?
            """,
            (
                character["id"],
                quest_key
            )
        ).fetchone()

        if quest is None:
            connection.close()

            return send_json(
                self,
                {
                    "error":
                    "Quest nicht angenommen."
                },
                400
            )

        if quest["status"] != "bereit":
            connection.close()

            return send_json(
                self,
                {
                    "error":
                    "Diese Quest ist noch nicht abgeschlossen."
                },
                400
            )

        connection.execute(
            """
            UPDATE characters
            SET gold = gold + ?
            WHERE id = ?
            """,
            (
                quest["reward_gold"],
                character["id"]
            )
        )

        add_experience(
            connection,
            character["id"],
            quest["reward_experience"]
        )

        connection.execute(
            """
            UPDATE character_quests
            SET status = 'abgeschlossen'
            WHERE character_id = ?
              AND quest_id = ?
            """,
            (
                character["id"],
                quest["id"]
            )
        )

        connection.commit()
        connection.close()

        return send_json(
            self,
            {
                "success": True,
                "message":
                "Quest abgeschlossen.",
                "experience":
                quest["reward_experience"],
                "gold":
                quest["reward_gold"]
            }
        )

    def use_item(self, data):
        account_id = get_session(self)

        if not account_id:
            return send_json(
                self,
                {
                    "error":
                    "Du bist nicht angemeldet."
                },
                401
            )

        item_name = str(
            data.get("item_name", "")
        )

        connection = db()

        character = get_character(account_id)

        if character is None:
            connection.close()

            return send_json(
                self,
                {
                    "error":
                    "Charakter nicht gefunden."
                },
                404
            )

        item = connection.execute(
            """
            SELECT
                inventory.amount,
                items.id,
                items.name
            FROM inventory
            JOIN items
                ON items.id = inventory.item_id
            WHERE inventory.character_id = ?
              AND items.name = ?
            """,
            (
                character["id"],
                item_name
            )
        ).fetchone()

        if item is None or item["amount"] <= 0:
            connection.close()

            return send_json(
                self,
                {
                    "error":
                    "Dieser Gegenstand ist nicht im Inventar."
                },
                400
            )

        if item["name"] == "Heiltrank":
            new_hp = min(
                character["max_hp"],
                character["hp"] + 30
            )

            connection.execute(
                """
                UPDATE characters
                SET hp = ?
                WHERE id = ?
                """,
                (
                    new_hp,
                    character["id"]
                )
            )

            message = (
                "Du hast einen Heiltrank benutzt "
                "und 30 Lebenspunkte wiederhergestellt."
            )

        else:
            connection.close()

            return send_json(
                self,
                {
                    "error":
                    "Dieser Gegenstand kann momentan nicht benutzt werden."
                },
                400
            )

        new_amount = item["amount"] - 1

        connection.execute(
            """
            UPDATE inventory
            SET amount = ?
            WHERE character_id = ?
              AND item_id = ?
            """,
            (
                new_amount,
                character["id"],
                item["id"]
            )
        )

        connection.commit()
        connection.close()

        return send_json(
            self,
            {
                "success": True,
                "message": message
            }
        )


def main():
    init_database()

    server = ThreadingHTTPServer(
        (HOST, PORT),
        GameHandler
    )

    print(
        f"Server läuft auf http://127.0.0.1:{PORT}"
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Server wird beendet.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
