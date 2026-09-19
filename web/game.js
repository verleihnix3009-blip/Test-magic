const auth = document.getElementById("auth");
const game = document.getElementById("game");

const usernameInput = document.getElementById("username");
const passwordInput = document.getElementById("password");
const characterNameInput = document.getElementById("characterName");

const registerButton = document.getElementById("registerButton");
const loginButton = document.getElementById("loginButton");
const logoutButton = document.getElementById("logoutButton");

const authMessage = document.getElementById("authMessage");
const gameMessage = document.getElementById("gameMessage");

const characterNameDisplay =
    document.getElementById("characterNameDisplay");

const levelElement =
    document.getElementById("level");

const hpElement =
    document.getElementById("hp");

const experienceElement =
    document.getElementById("experience");

const goldElement =
    document.getElementById("gold");

const positionElement =
    document.getElementById("position");

const playerElement =
    document.querySelector(".player");

const battleButton =
    document.getElementById("battleButton");

const battleLog =
    document.getElementById("battleLog");

const questButton =
    document.getElementById("questButton");

const questPanel =
    document.getElementById("questPanel");

const inventoryElement =
    document.getElementById("inventory");


async function api(url, options = {}) {
    const response = await fetch(url, {
        credentials: "same-origin",
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {})
        }
    });

    let data;

    try {
        data = await response.json();
    } catch {
        data = {
            error: "Ungültige Serverantwort."
        };
    }

    if (!response.ok) {
        throw new Error(
            data.error || "Es ist ein Fehler aufgetreten."
        );
    }

    return data;
}


function showAuthMessage(message, error = false) {
    authMessage.textContent = message;

    authMessage.className =
        error
            ? "message error"
            : "message success";
}


function showGameMessage(message, error = false) {
    gameMessage.textContent = message;

    gameMessage.className =
        error
            ? "error"
            : "success";
}


function showGame() {
    auth.classList.add("hidden");
    game.classList.remove("hidden");
}


function showAuth() {
    game.classList.add("hidden");
    auth.classList.remove("hidden");
}


function updatePlayerPosition(x, y) {
    positionElement.textContent =
        `Position: ${x}, ${y}`;

    const percentX =
        (x / 20) * 100;

    const percentY =
        (y / 20) * 100;

    playerElement.style.left =
        `${percentX}%`;

    playerElement.style.top =
        `${percentY}%`;
}


function renderQuest(quests) {
    if (!quests || quests.length === 0) {
        questPanel.textContent =
            "Du hast momentan keine Quest.";
        return;
    }

    questPanel.innerHTML = "";

    for (const quest of quests) {
        const wrapper =
            document.createElement("div");

        wrapper.className = "quest";

        const title =
            document.createElement("h3");

        title.textContent =
            quest.name;

        const description =
            document.createElement("p");

        description.textContent =
            quest.description;

        const progress =
            document.createElement("p");

        progress.textContent =
            `Fortschritt: ${quest.progress} / ${quest.required_amount}`;

        wrapper.appendChild(title);
        wrapper.appendChild(description);
        wrapper.appendChild(progress);

        if (quest.status === "bereit") {
            const completeButton =
                document.createElement("button");

            completeButton.textContent =
                "Quest abschließen";

            completeButton.addEventListener(
                "click",
                async () => {
                    try {
                        const result =
                            await api(
                                "/api/quest/complete",
                                {
                                    method: "POST",
                                    body: JSON.stringify({
                                        quest_key:
                                            quest.quest_key
                                    })
                                }
                            );

                        showGameMessage(
                            `${result.message} +${result.experience} Erfahrung, +${result.gold} Gold.`
                        );

                        await loadState();

                    } catch (error) {
                        showGameMessage(
                            error.message,
                            true
                        );
                    }
                }
            );

            wrapper.appendChild(
                completeButton
            );
        }

        if (quest.status === "abgeschlossen") {
            const completed =
                document.createElement("p");

            completed.className =
                "success";

            completed.textContent =
                "Abgeschlossen";

            wrapper.appendChild(
                completed
            );
        }

        questPanel.appendChild(
            wrapper
        );
    }
}


function renderInventory(inventory) {
    if (!inventory || inventory.length === 0) {
        inventoryElement.textContent =
            "Dein Inventar ist leer.";
        return;
    }

    inventoryElement.innerHTML = "";

    for (const item of inventory) {
        const wrapper =
            document.createElement("div");

        wrapper.className =
            "inventory-item";

        const title =
            document.createElement("h3");

        title.textContent =
            `${item.name} × ${item.amount}`;

        const description =
            document.createElement("p");

        description.textContent =
            item.description;

        wrapper.appendChild(title);
        wrapper.appendChild(description);

        if (
            item.name === "Heiltrank"
            && item.amount > 0
        ) {
            const useButton =
                document.createElement("button");

            useButton.textContent =
                "Heiltrank benutzen";

            useButton.addEventListener(
                "click",
                async () => {
                    try {
                        const result =
                            await api(
                                "/api/item/use",
                                {
                                    method: "POST",
                                    body: JSON.stringify({
                                        item_name:
                                            item.name
                                    })
                                }
                            );

                        showGameMessage(
                            result.message
                        );

                        await loadState();

                    } catch (error) {
                        showGameMessage(
                            error.message,
                            true
                        );
                    }
                }
            );

            wrapper.appendChild(
                useButton
            );
        }

        inventoryElement.appendChild(
            wrapper
        );
    }
}


async function loadState() {
    try {
        const result =
            await api("/api/state");

        if (!result.logged_in) {
            showAuth();
            return;
        }

        showGame();

        const state =
            result.state;

        if (!state || !state.character) {
            return;
        }

        const character =
            state.character;

        characterNameDisplay.textContent =
            character.name;

        levelElement.textContent =
            character.level;

        hpElement.textContent =
            `${character.hp} / ${character.max_hp}`;

        experienceElement.textContent =
            character.experience;

        goldElement.textContent =
            character.gold;

        updatePlayerPosition(
            character.x,
            character.y
        );

        renderQuest(
            state.quests
        );

        renderInventory(
            state.inventory
        );

    } catch (error) {
        showAuthMessage(
            error.message,
            true
        );
    }
}


registerButton.addEventListener(
    "click",
    async () => {
        const username =
            usernameInput.value.trim();

        const password =
            passwordInput.value;

        const characterName =
            characterNameInput.value.trim();

        try {
            const result =
                await api(
                    "/api/register",
                    {
                        method: "POST",
                        body: JSON.stringify({
                            username,
                            password,
                            character_name:
                                characterName
                        })
                    }
                );

            showAuthMessage(
                result.message
            );

            await loadState();

        } catch (error) {
            showAuthMessage(
                error.message,
                true
            );
        }
    }
);


loginButton.addEventListener(
    "click",
    async () => {
        const username =
            usernameInput.value.trim();

        const password =
            passwordInput.value;

        try {
            const result =
                await api(
                    "/api/login",
                    {
                        method: "POST",
                        body: JSON.stringify({
                            username,
                            password
                        })
                    }
                );

            showAuthMessage(
                result.message
            );

            await loadState();

        } catch (error) {
            showAuthMessage(
                error.message,
                true
            );
        }
    }
);


logoutButton.addEventListener(
    "click",
    async () => {
        try {
            await api(
                "/api/logout",
                {
                    method: "POST"
                }
            );

            showAuth();
            showAuthMessage(
                "Du wurdest abgemeldet."
            );

        } catch (error) {
            showGameMessage(
                error.message,
                true
            );
        }
    }
);


document
    .querySelectorAll(
        "[data-direction]"
    )
    .forEach(button => {

        button.addEventListener(
            "click",
            async () => {

                try {
                    const result =
                        await api(
                            "/api/move",
                            {
                                method: "POST",
                                body: JSON.stringify({
                                    direction:
                                        button.dataset.direction
                                })
                            }
                        );

                    updatePlayerPosition(
                        result.x,
                        result.y
                    );

                } catch (error) {
                    showGameMessage(
                        error.message,
                        true
                    );
                }
            }
        );

    });


battleButton.addEventListener(
    "click",
    async () => {

        battleButton.disabled = true;

        try {
            const result =
                await api(
                    "/api/battle",
                    {
                        method: "POST",
                        body: JSON.stringify({
                            monster_id:
                                "waldkobold"
                        })
                    }
                );

            battleLog.textContent =
                result.log.join("\n")
                + "\n\n"
                + result.message
                + `\n+${result.experience} Erfahrung`
                + `\n+${result.gold} Gold`;

            if (result.quest_ready) {
                showGameMessage(
                    "Deine Quest ist bereit zum Abschließen."
                );
            }

            await loadState();

        } catch (error) {
            showGameMessage(
                error.message,
                true
            );

        } finally {
            battleButton.disabled = false;
        }
    }
);


questButton.addEventListener(
    "click",
    async () => {

        try {
            const result =
                await api(
                    "/api/quest/accept",
                    {
                        method: "POST",
                        body: JSON.stringify({
                            quest_key:
                                "erster_waldkobold"
                        })
                    }
                );

            showGameMessage(
                result.message
            );

            await loadState();

        } catch (error) {
            showGameMessage(
                error.message,
                true
            );
        }
    }
);


loadState();
