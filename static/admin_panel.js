(function () {
  const baseUrl = window.location.origin;

  let accessToken = null;
  let currentUserRole = "admin"; // será inferido a partir do JWT
  let currentUserId = null;
  let lineOwnerWrapper = null;
  let currentUsername = null;

  const sectionLogin = document.getElementById("section-login");
  const adminWrapper = document.getElementById("admin-wrapper");
  const panelNameEl = document.getElementById("panel-name");
  const navbarUserInfo = document.getElementById("navbar-user-info");
  // Dashboard sync elements
  const btnSyncChannels = document.getElementById("btn-sync-channels");
  const btnSyncVod = document.getElementById("btn-sync-vod");
  const btnSyncVodNoEpisodes = document.getElementById("btn-sync-vod-no-episodes");
  const btnSyncVodMovies = document.getElementById("btn-sync-vod-movies");
  const btnSyncVodSeries = document.getElementById("btn-sync-vod-series");
  const btnSyncVodPosters = document.getElementById("btn-sync-vod-posters");
  const syncChannelsResult = document.getElementById("sync-channels-result");
  const syncVodResult = document.getElementById("sync-vod-result");
  const vodSyncModalEl = document.getElementById("vodSyncModal");
  const vodSyncModal = vodSyncModalEl ? new bootstrap.Modal(vodSyncModalEl) : null;
  const vodSyncStatusEl = document.getElementById("vod-sync-status");
  const vodSyncLogEl = document.getElementById("vod-sync-log");
  let vodSyncPollTimer = null;
  const messageModalEl = document.getElementById("messageModal");
  const messageModal = messageModalEl ? new bootstrap.Modal(messageModalEl) : null;
  const messageModalTitle = document.getElementById("messageModalTitle");
  const messageModalBody = document.getElementById("messageModalBody");
  const btnMessageCopy = document.getElementById("btn-message-copy");
  const confirmModalEl = document.getElementById("confirmModal");
  const confirmModal = confirmModalEl ? new bootstrap.Modal(confirmModalEl) : null;
  const confirmModalTitle = document.getElementById("confirmModalTitle");
  const confirmModalBody = document.getElementById("confirmModalBody");
  const confirmModalOk = document.getElementById("confirmModalOk");
  const serverMessageBox = document.getElementById("server-message-box");
  const serverMessageText = document.getElementById("server-message-text");
  const panelSettingsCard = document.getElementById("panel-settings-card");
  const formPanelSettings = document.getElementById("form-panel-settings");
  const inputPanelName = document.getElementById("input-panel-name");
  const inputServerMessage = document.getElementById("input-server-message");
  const inputTimezone = document.getElementById("input-timezone");
  const inputLoginTheme = document.getElementById("input-login-theme");
  const inputPanelTheme = document.getElementById("input-panel-theme");

  function applyLoginTheme(theme) {
    if (!sectionLogin) return;
    const themes = ["default", "mountain", "beach", "city", "forest", "desert", "aurora", "space", "ocean"];

    // Normaliza valores antigos ou inesperados do banco
    let tNormalized = (theme || "").toString().toLowerCase();
    if (tNormalized === "floresta") tNormalized = "forest";

    themes.forEach((t) => {
      sectionLogin.classList.remove("theme-" + t);
    });
    const safe = themes.includes(tNormalized) ? tNormalized : "default";
    sectionLogin.classList.add("theme-" + safe);
  }

  function applyPanelTheme(theme) {
    if (!adminWrapper) return;
    const themes = ["default", "dark", "darkblue", "slate", "emerald"];

    const normalized = (theme || "").toString().toLowerCase();
    themes.forEach((t) => {
      adminWrapper.classList.remove("panel-theme-" + t);
    });
    const safe = themes.includes(normalized) ? normalized : "default";
    adminWrapper.classList.add("panel-theme-" + safe);
  }

  function parseJwt(token) {
    const parts = (token || "").split(".");
    if (parts.length !== 3) return {};
    try {
      return JSON.parse(atob(parts[1]));
    } catch (e) {
      return {};
    }
  }

  // ===== Dashboard: sincronização de canais e VOD =====
  if (btnSyncChannels) {
    btnSyncChannels.addEventListener("click", () => {
      if (syncChannelsResult) {
        syncChannelsResult.textContent = "Sincronizando canais...";
      }
      apiRequest("POST", "/admin/sync/channels")
        .then((res) => {
          if (syncChannelsResult) {
            syncChannelsResult.textContent = JSON.stringify(res, null, 2);
          }
        })
        .catch((err) => {
          if (syncChannelsResult) {
            syncChannelsResult.textContent = "Erro ao sincronizar canais: " + err.message;
          }
          showMessageModal("error", "Erro ao sincronizar canais: " + err.message);
        });
    });
  }

  if (btnSyncVodNoEpisodes) {
    btnSyncVodNoEpisodes.addEventListener("click", () => {
      // Usa o mesmo modal + polling da sync completa, mas chamando o job rápido
      if (!vodSyncModal) {
        // fallback: sem modal, apenas texto no <pre>
        if (syncVodResult) {
          syncVodResult.textContent =
            "Sincronizando VOD + episódios (sem detalhes de episódios na TMDB)...";
        }
        apiRequest("POST", "/admin/sync/vod/contents-only")
          .then((res) => {
            if (syncVodResult) {
              syncVodResult.textContent = JSON.stringify(res, null, 2);
            }
          })
          .catch((err) => {
            if (syncVodResult) {
              syncVodResult.textContent =
                "Erro ao sincronizar VOD (sem detalhes de episódios): " + err.message;
            }
            showMessageModal(
              "error",
              "Erro ao sincronizar VOD (sem detalhes de episódios): " + err.message,
            );
          });
        return;
      }

      if (vodSyncStatusEl) {
        vodSyncStatusEl.textContent =
          "Sincronizando VOD + episódios (sem detalhes de episódios na TMDB)...";
      }
      if (vodSyncLogEl) {
        vodSyncLogEl.textContent = "";
      }

      if (vodSyncPollTimer) {
        clearInterval(vodSyncPollTimer);
        vodSyncPollTimer = null;
      }

      vodSyncModal.show();

      apiRequest("POST", "/admin/sync/vod/start-fast")
        .then(() => {
          vodSyncPollTimer = setInterval(() => {
            apiRequest("GET", "/admin/sync/vod/progress")
              .then((p) => {
                if (vodSyncStatusEl) {
                  const step = p.step || "";
                  const current = p.current ?? 0;
                  const total = p.total ?? 0;
                  vodSyncStatusEl.textContent = `Etapa (rápida): ${step} | ${current}/${total}`;
                }
                if (vodSyncLogEl) {
                  vodSyncLogEl.textContent = JSON.stringify(p, null, 2);
                }

                if (!p.running || p.error) {
                  if (vodSyncPollTimer) {
                    clearInterval(vodSyncPollTimer);
                    vodSyncPollTimer = null;
                  }
                  if (p.error) {
                    showMessageModal(
                      "error",
                      "Erro na sincronização rápida de VOD: " + p.error,
                    );
                  }
                }
              })
              .catch((err) => {
                if (vodSyncStatusEl) {
                  vodSyncStatusEl.textContent =
                    "Erro ao consultar progresso (rápido): " + err.message;
                }
                if (vodSyncPollTimer) {
                  clearInterval(vodSyncPollTimer);
                  vodSyncPollTimer = null;
                }
                showMessageModal(
                  "error",
                  "Erro ao consultar progresso de VOD (rápido): " + err.message,
                );
              });
          }, 2000);
        })
        .catch((err) => {
          if (vodSyncStatusEl) {
            vodSyncStatusEl.textContent =
              "Erro ao iniciar sincronização rápida de VOD: " + err.message;
          }
          showMessageModal(
            "error",
            "Erro ao iniciar sincronização rápida de VOD: " + err.message,
          );
        });
    });
  }

  if (btnSyncVod) {
    btnSyncVod.addEventListener("click", () => {
      // Sincronização completa usa job assíncrono + modal de progresso
      if (!vodSyncModal) {
        // fallback simples se o modal não estiver disponível
        if (syncVodResult) {
          syncVodResult.textContent = "Iniciando sincronização completa de VOD...";
        }
        apiRequest("POST", "/admin/sync/vod")
          .then((res) => {
            if (syncVodResult) {
              syncVodResult.textContent = JSON.stringify(res, null, 2);
            }
          })
          .catch((err) => {
            if (syncVodResult) {
              syncVodResult.textContent = "Erro ao sincronizar VOD: " + err.message;
            }
            showMessageModal("error", "Erro ao sincronizar VOD: " + err.message);
          });
        return;
      }

      // Reseta status/log do modal
      if (vodSyncStatusEl) {
        vodSyncStatusEl.textContent = "Iniciando sincronização completa de VOD...";
      }
      if (vodSyncLogEl) {
        vodSyncLogEl.textContent = "";
      }

      // Cancela qualquer polling anterior
      if (vodSyncPollTimer) {
        clearInterval(vodSyncPollTimer);
        vodSyncPollTimer = null;
      }

      vodSyncModal.show();

      apiRequest("POST", "/admin/sync/vod/start")
        .then(() => {
          // Inicia polling de progresso a cada 2s
          vodSyncPollTimer = setInterval(() => {
            apiRequest("GET", "/admin/sync/vod/progress")
              .then((p) => {
                if (vodSyncStatusEl) {
                  const step = p.step || "";
                  const current = p.current ?? 0;
                  const total = p.total ?? 0;
                  vodSyncStatusEl.textContent = `Etapa: ${step} | ${current}/${total}`;
                }
                if (vodSyncLogEl) {
                  const line = JSON.stringify(p, null, 2);
                  vodSyncLogEl.textContent = line;
                }

                // Encerra polling quando não estiver mais rodando ou em caso de erro
                if (!p.running || p.error) {
                  if (vodSyncPollTimer) {
                    clearInterval(vodSyncPollTimer);
                    vodSyncPollTimer = null;
                  }
                  if (p.error) {
                    showMessageModal("error", "Erro na sincronização de VOD: " + p.error);
                  }
                }
              })
              .catch((err) => {
                if (vodSyncStatusEl) {
                  vodSyncStatusEl.textContent = "Erro ao consultar progresso: " + err.message;
                }
                if (vodSyncPollTimer) {
                  clearInterval(vodSyncPollTimer);
                  vodSyncPollTimer = null;
                }
                showMessageModal("error", "Erro ao consultar progresso de VOD: " + err.message);
              });
          }, 2000);
        })
        .catch((err) => {
          if (vodSyncStatusEl) {
            vodSyncStatusEl.textContent = "Erro ao iniciar sincronização: " + err.message;
          }
          showMessageModal("error", "Erro ao iniciar sincronização de VOD: " + err.message);
        });
    });
  }

  if (btnSyncVodMovies) {
    btnSyncVodMovies.addEventListener("click", () => {
      if (syncVodResult) {
        syncVodResult.textContent = "Sincronizando apenas filmes VOD...";
      }
      apiRequest("POST", "/admin/sync/vod/movies")
        .then((res) => {
          if (syncVodResult) {
            syncVodResult.textContent = JSON.stringify(res, null, 2);
          }
        })
        .catch((err) => {
          if (syncVodResult) {
            syncVodResult.textContent = "Erro ao sincronizar filmes VOD: " + err.message;
          }
          showMessageModal("error", "Erro ao sincronizar filmes VOD: " + err.message);
        });
    });
  }

  if (btnSyncVodSeries) {
    btnSyncVodSeries.addEventListener("click", () => {
      if (syncVodResult) {
        syncVodResult.textContent = "Sincronizando apenas séries VOD...";
      }
      apiRequest("POST", "/admin/sync/vod/series")
        .then((res) => {
          if (syncVodResult) {
            syncVodResult.textContent = JSON.stringify(res, null, 2);
          }
        })
        .catch((err) => {
          if (syncVodResult) {
            syncVodResult.textContent = "Erro ao sincronizar séries VOD: " + err.message;
          }
          showMessageModal("error", "Erro ao sincronizar séries VOD: " + err.message);
        });
    });
  }

  if (btnSyncVodPosters) {
    btnSyncVodPosters.addEventListener("click", () => {
      if (syncVodResult) {
        syncVodResult.textContent = "Atualizando apenas capas VOD via TMDB...";
      }
      apiRequest("POST", "/admin/sync/vod/posters-only")
        .then((res) => {
          if (syncVodResult) {
            syncVodResult.textContent = JSON.stringify(res, null, 2);
          }
        })
        .catch((err) => {
          if (syncVodResult) {
            syncVodResult.textContent = "Erro ao atualizar capas VOD: " + err.message;
          }
          showMessageModal("error", "Erro ao atualizar capas VOD: " + err.message);
        });
    });
  }

  function showSection(id) {
    document.querySelectorAll(".admin-section").forEach((el) => {
      el.classList.add("d-none");
    });
    const sec = document.getElementById("section-" + id);
    if (sec) sec.classList.remove("d-none");

    document.querySelectorAll(".navbar-nav .nav-link").forEach((el) => {
      el.classList.remove("active");
      if (el.getAttribute("data-section") === id) {
        el.classList.add("active");
      }
    });

    // Persiste a última seção visitada para restaurar após reload
    try {
      localStorage.setItem("xtream_panel_section", id);
    } catch (_) {}
  }

  function resetNavVisibility() {
    document.querySelectorAll(".navbar-nav .nav-link").forEach((el) => {
      const li = el.closest("li");
      if (li) li.style.display = "";
    });
  }

  function clearLoadedData() {
    if (navbarUserInfo) {
      navbarUserInfo.textContent = "";
    }
    const usersBody = document.querySelector("#table-users tbody");
    const linesUsersBodyEl = document.querySelector("#table-lines-users tbody");
    const linesTestsBodyEl = document.querySelector("#table-lines-tests tbody");
    const channelsBodyEl = document.querySelector("#table-channels tbody");
    const vodBodyEl = document.querySelector("#table-vod tbody");

    if (usersBody) usersBody.innerHTML = "";
    if (linesUsersBodyEl) linesUsersBodyEl.innerHTML = "";
    if (linesTestsBodyEl) linesTestsBodyEl.innerHTML = "";
    if (channelsBodyEl) channelsBodyEl.innerHTML = "";
    if (vodBodyEl) vodBodyEl.innerHTML = "";
  }

  function resetSessionState() {
    accessToken = null;
    currentUserRole = "admin";
    currentUserId = null;
    currentUsername = null;
    clearLoadedData();
    resetNavVisibility();
    if (panelNameEl) panelNameEl.textContent = "Xtream Python";
    if (serverMessageBox) {
      serverMessageBox.classList.add("d-none");
    }
  }
  function authHeaders() {
    if (!accessToken) return {};
    return { Authorization: "Bearer " + accessToken };
  }

  async function apiRequest(method, path, body) {
    const opts = {
      method,
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
      },
    };
    if (body !== undefined) {
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(baseUrl + path, opts);
    if (!res.ok) {
      let detail = await res.text();
      try {
        const j = JSON.parse(detail);
        detail = j.detail || JSON.stringify(j);
      } catch (_) {}
      throw new Error(detail || `HTTP ${res.status}`);
    }
    if (res.status === 204) return null;
    return await res.json();
  }

  async function loadPanelSettings() {
    if (!accessToken) return;
    try {
      const data = await apiRequest("GET", "/admin/settings/");
      if (panelNameEl && data.panel_name) {
        panelNameEl.textContent = data.panel_name;
      }
      if (data.panel_name) {
        document.title = `${data.panel_name} - Painel Xtream`;
      }
      if (inputPanelName) {
        inputPanelName.value = data.panel_name || "";
      }
      const msg = data.server_message || "";
      if (serverMessageBox && serverMessageText) {
        if (msg) {
          serverMessageText.textContent = msg;
          serverMessageBox.classList.remove("d-none");
        } else {
          serverMessageText.textContent = "";
          serverMessageBox.classList.add("d-none");
        }
      }
      if (inputServerMessage) {
        inputServerMessage.value = msg;
      }

      if (inputTimezone) {
        inputTimezone.value = data.timezone || inputTimezone.value || "UTC-3";
      }

      const themeOptions = ["default", "mountain", "beach", "city", "forest", "desert", "aurora", "space", "ocean"];
      let themeFromServer = data.login_theme || (inputLoginTheme && inputLoginTheme.value) || "default";
      if (themeFromServer === "floresta") themeFromServer = "forest";
      if (!themeOptions.includes(themeFromServer)) themeFromServer = "default";

      if (inputLoginTheme) {
        inputLoginTheme.value = themeFromServer;
      }

      applyLoginTheme(themeFromServer);

      // Tema do painel (pós-login)
      const panelThemeOptions = ["default", "dark", "darkblue", "slate", "emerald"];
      let panelThemeFromServer = data.panel_theme || (inputPanelTheme && inputPanelTheme.value) || "default";
      if (!panelThemeOptions.includes(panelThemeFromServer)) panelThemeFromServer = "default";

      if (inputPanelTheme) {
        inputPanelTheme.value = panelThemeFromServer;
      }

      applyPanelTheme(panelThemeFromServer);

      // Apenas admins podem ver o card de configurações
      if (panelSettingsCard) {
        if (currentUserRole === "admin") {
          panelSettingsCard.classList.remove("d-none");
        } else {
          panelSettingsCard.classList.add("d-none");
        }
      }
    } catch (err) {
      console.warn("Erro ao carregar configurações do painel", err);
    }
  }

  // LOGIN
  const formLogin = document.getElementById("form-login");
  const loginError = document.getElementById("login-error");
  lineOwnerWrapper = document.getElementById("line-owner-wrapper");
  if (formLogin) {
    formLogin.addEventListener("submit", async (e) => {
      e.preventDefault();
      loginError.style.display = "none";
      const formData = new FormData(formLogin);
      const username = formData.get("username");
      const password = formData.get("password");
      const body = new URLSearchParams();
      body.append("username", username);
      body.append("password", password);

      try {
        // Sempre reseta qualquer estado antigo antes de aplicar o novo login
        resetSessionState();

        const res = await fetch(baseUrl + "/admin/login", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body,
        });
        if (!res.ok) {
          const txt = await res.text();
          let msg = txt;
          try {
            const j = JSON.parse(txt);
            msg = j.detail || txt;
          } catch (_) {}
          throw new Error(msg || "Falha no login");
        }
        const data = await res.json();
        accessToken = data.access_token;
        try {
          localStorage.setItem("xtream_panel_token", accessToken);
        } catch (_) {}

        const payload = parseJwt(accessToken);
        currentUserRole = (payload.role || (payload.is_admin ? "admin" : "vendor") || "admin").toLowerCase();
        currentUserId = payload.sub || payload.user_id || null;
        currentUsername = payload.sub || null;

        if (currentUserRole === "vendor" && lineOwnerWrapper) {
          lineOwnerWrapper.style.display = "none";
        }

        sectionLogin.classList.add("hidden");
        adminWrapper.classList.remove("hidden");

        if (currentUserRole === "admin") {
          showSection("dashboard");
          loadUsers();
        } else {
          // Esconde seções que são apenas para admin (inclusive Dashboard e Configurações)
          resetNavVisibility();
          document
            .querySelectorAll(
              '[data-section="dashboard"], [data-section="users"], [data-section="categories"], [data-section="channels"], [data-section="vod"], [data-section="settings"]'
            )
            .forEach((el) => {
              const li = el.closest("li");
              if (li) li.style.display = "none";
            });
          showSection("lines");
        }

        await Promise.all([loadLines(), loadCurrentUserInfo(), loadPanelSettings()]);
      } catch (err) {
        loginError.textContent = err.message;
        loginError.style.display = "block";
      }
    });
  }

  // Navegação
  document.querySelectorAll(".navbar-nav .nav-link").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      const sec = el.getAttribute("data-section");

      // Para vendedores, só permitimos navegar para linhas e testes IPTV
      if (currentUserRole === "vendor" && sec !== "lines" && sec !== "tests") {
        return;
      }

      if (sec) showSection(sec);
      if (sec === "users") loadUsers();
      if (sec === "lines") {
        loadLinesUsers();
      }
      if (sec === "tests") {
        loadLinesTests();
      }
      if (sec === "channels") {
        loadChannels();
      }
      if (sec === "vod") {
        loadVod();
      }
    });
  });

  const btnLogout = document.getElementById("btn-logout");
  if (btnLogout) {
    btnLogout.addEventListener("click", () => {
      resetSessionState();
      try {
        localStorage.removeItem("xtream_panel_token");
      } catch (_) {}
      adminWrapper.classList.add("hidden");
      sectionLogin.classList.remove("hidden");
    });
  }

  // ===== Usuários de painel =====
  const formUser = document.getElementById("form-user");
  const tableUsersBody = document.querySelector("#table-users tbody");

  // ===== Tabelas de canais e VOD =====
  const tableChannelsBody = document.querySelector("#table-channels tbody");
  const tableVodBody = document.querySelector("#table-vod tbody");

  const userPanelModalEl = document.getElementById("userPanelModal");
  const userPanelModal = userPanelModalEl ? new bootstrap.Modal(userPanelModalEl) : null;
  const modalUserRole = document.getElementById("modal-user-role");
  const modalUserPanelExpires = document.getElementById("modal-user-panel-expires");
  const modalUserPanelCredits = document.getElementById("modal-user-panel-credits");
  const btnUserPanelSave = document.getElementById("btn-user-panel-save");
  let editingUserPanelId = null;

  async function loadChannels() {
    if (!tableChannelsBody || !accessToken) return;
    tableChannelsBody.innerHTML = "";
    try {
      const channels = await apiRequest("GET", "/admin/channels/");
      channels.forEach((ch) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${ch.id}</td>
          <td>${ch.name}</td>
          <td>${ch.category_id ?? "-"}</td>
          <td>${ch.is_premium ? "Sim" : "Não"}</td>
          <td>${ch.is_adult ? "Sim" : "Não"}</td>
          <td>${ch.is_available ? "Sim" : "Não"}</td>
        `;
        tableChannelsBody.appendChild(tr);
      });
    } catch (err) {
      console.error("Erro ao carregar canais", err);
      showMessageModal("error", "Erro ao carregar canais: " + err.message);
    }
  }

  async function loadVod() {
    if (!tableVodBody || !accessToken) return;
    tableVodBody.innerHTML = "";
    try {
      const items = await apiRequest("GET", "/admin/vod/");
      items.forEach((v) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${v.id}</td>
          <td>${v.title}</td>
          <td>${v.type}</td>
          <td>${v.category || "-"}</td>
          <td>${v.tmdb_id ?? "-"}</td>
          <td>${v.is_available ? "Sim" : "Não"}</td>
        `;
        tableVodBody.appendChild(tr);
      });
    } catch (err) {
      console.error("Erro ao carregar VOD", err);
      showMessageModal("error", "Erro ao carregar VOD: " + err.message);
    }
  }

  async function loadUsers() {
    if (!tableUsersBody || !accessToken) return;
    tableUsersBody.innerHTML = "";
    try {
      const users = await apiRequest("GET", "/admin/users/");
      users.forEach((u) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${u.id}</td>
          <td>${u.username}</td>
          <td>${u.is_active ? "Sim" : "Não"}</td>
          <td>${u.role || (u.is_admin ? "admin" : "vendor")}</td>
          <td>${u.panel_expires_at || "-"}</td>
          <td>${u.panel_credits ?? 0}</td>
          <td>${u.expires_at || "-"}</td>
          <td>${u.max_connections}</td>
          <td>
            <button class="btn btn-sm btn-outline-primary btn-user-panel" data-id="${u.id}">Painel</button>
            <button class="btn btn-sm btn-outline-danger btn-user-del" data-id="${u.id}">Excluir</button>
          </td>
        `;
        tableUsersBody.appendChild(tr);
      });

      // Botões de edição de painel (role, validade, créditos)
      document.querySelectorAll(".btn-user-panel").forEach((btn) => {
        btn.addEventListener("click", () => {
          const id = btn.getAttribute("data-id");
          const row = btn.closest("tr");
          if (!row || !userPanelModal) return;

          editingUserPanelId = id;
          const role = row.children[3].textContent.trim() || "vendor";
          const panelExpires = row.children[4].textContent.trim();
          const credits = row.children[5].textContent.trim();

          if (modalUserRole) modalUserRole.value = role.toLowerCase();
          if (modalUserPanelExpires) {
            modalUserPanelExpires.value = panelExpires && panelExpires !== "-" ? panelExpires : "";
          }
          if (modalUserPanelCredits) {
            modalUserPanelCredits.value = credits || "0";
          }

          userPanelModal.show();
        });
      });

      // Botões de exclusão de usuário
      document.querySelectorAll(".btn-user-del").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = btn.getAttribute("data-id");
          if (!id) return;

          const ok = await showConfirmDialog("Tem certeza que deseja excluir este usuário do painel?", {
            title: "Excluir usuário",
          });
          if (!ok) return;

          apiRequest("DELETE", `/admin/users/${id}`)
            .then(() => {
              loadUsers();
            })
            .catch((err) => {
              showMessageModal("error", "Erro ao excluir usuário: " + err.message);
            });
        });
      });
    } catch (err) {
      console.error("Erro ao carregar usuários", err);
    }
  }

  if (formUser) {
    formUser.addEventListener("submit", (e) => {
      e.preventDefault();
      const fd = new FormData(formUser);
      const payload = {
        username: fd.get("username"),
        password: fd.get("password"),
        role: fd.get("role") || "admin",
        panel_expires_at: fd.get("panel_expires_at") || null,
        panel_credits: parseInt(fd.get("panel_credits") || "0", 10),
        is_active: fd.get("is_active") === "on",
      };
      apiRequest("POST", "/admin/users/", payload)
        .then(() => {
          formUser.reset();
          loadUsers();
        })
        .catch((err) => showMessageModal("error", "Erro ao criar usuário: " + err.message));
    });
  }

  if (btnUserPanelSave) {
    btnUserPanelSave.addEventListener("click", () => {
      if (!editingUserPanelId) return;

      const payload = {};

      if (modalUserRole && modalUserRole.value) {
        payload.role = modalUserRole.value.toLowerCase();
      }

      if (modalUserPanelExpires) {
        const val = modalUserPanelExpires.value.trim();
        payload.panel_expires_at = val || null;
      }

      if (modalUserPanelCredits) {
        const creditsTxt = modalUserPanelCredits.value.trim();
        if (creditsTxt !== "") {
          payload.panel_credits = parseInt(creditsTxt, 10);
        }
      }

      apiRequest("PUT", `/admin/users/${editingUserPanelId}/panel`, payload)
        .then(() => {
          if (userPanelModal) userPanelModal.hide();
          editingUserPanelId = null;
          loadUsers();
        })
        .catch((err) => {
          showMessageModal("error", "Erro ao salvar dados de painel: " + err.message);
        });
    });
  }

  // ===== Linhas IPTV =====
  const formLine = document.getElementById("form-line");
  const tableLinesUsersBody = document.querySelector("#table-lines-users tbody");
  const linesFilterQuery = document.getElementById("lines-filter-query");
  const linesFilterApply = document.getElementById("lines-filter-apply");
  const linesFilterStatus = document.getElementById("lines-filter-status");
  const linesFilterExpiry = document.getElementById("lines-filter-expiry");
  const linesSelectAll = document.getElementById("lines-select-all");
  const bulkDeleteLinesBtn = document.getElementById("bulk-delete-lines");
  const bulkRenewLinesBtn = document.getElementById("bulk-renew-lines");
  const bulkChangeOwnerLinesBtn = document.getElementById("bulk-change-owner-lines");
  const tableLinesTestsBody = document.querySelector("#table-lines-tests tbody");
  const testsFilterQuery = document.getElementById("tests-filter-query");
  const testsFilterApply = document.getElementById("tests-filter-apply");
  const testsFilterStatus = document.getElementById("tests-filter-status");
  const testsFilterExpiry = document.getElementById("tests-filter-expiry");
  const testsSelectAll = document.getElementById("tests-select-all");
  const bulkDeleteTestsBtn = document.getElementById("bulk-delete-tests");
  const bulkPromoteTestsBtn = document.getElementById("bulk-promote-tests");
  const lineEditModalEl = document.getElementById("lineEditModal");
  const lineEditModal = lineEditModalEl ? new bootstrap.Modal(lineEditModalEl) : null;
  const modalLinePassword = null; // senha não é mais editável
  const modalLineActive = document.getElementById("modal-line-active");
  const modalLineMonths = document.getElementById("modal-line-months");
  const modalLineMaxConnections = document.getElementById("modal-line-max-connections");
  const btnLineSave = document.getElementById("btn-line-save");
  let editingLineId = null;

  const btnLineTest3h = document.getElementById("btn-line-test-3h");
  const lineTestModalEl = document.getElementById("lineTestModal");
  const lineTestModal = lineTestModalEl ? new bootstrap.Modal(lineTestModalEl) : null;
  const testUsernameInput = document.getElementById("test-username");
  const testPasswordInput = document.getElementById("test-password");
  const btnLineTestConfirm = document.getElementById("btn-line-test-confirm");

  const lineCreateModalEl = document.getElementById("lineCreateModal");
  const lineCreateModal = lineCreateModalEl ? new bootstrap.Modal(lineCreateModalEl) : null;
  const createUsernameInput = document.getElementById("create-username");
  const createPasswordInput = document.getElementById("create-password");
  const createNameInput = document.getElementById("create-name");
  const createPhoneInput = document.getElementById("create-phone");
  const createEmailInput = document.getElementById("create-email");
  const createMonthsInput = document.getElementById("create-months");
  const createMaxConnectionsInput = document.getElementById("create-max-connections");
  const btnOpenLineCreate = document.getElementById("btn-open-line-create");
  const btnLineCreateConfirm = document.getElementById("btn-line-create-confirm");

  console.log("[IPTV] lineCreateModalEl:", !!lineCreateModalEl, "btnOpenLineCreate:", !!btnOpenLineCreate);

  // Abertura do modal de criação de linha normal
  if (btnOpenLineCreate) {
    btnOpenLineCreate.addEventListener("click", () => {
      console.log("[IPTV] Clique em Nova linha");
      if (!lineCreateModal) {
        console.warn("[IPTV] lineCreateModal não inicializado");
        return;
      }
      if (!createUsernameInput || !createPasswordInput) {
        console.warn("[IPTV] Campos do modal não encontrados");
        return;
      }
      // Gera usuário e senha automaticamente e guarda nos campos ocultos
      createUsernameInput.value = generateRandomId(6);
      createPasswordInput.value = generateRandomId(6);
      if (createMonthsInput) createMonthsInput.value = "1";
      if (createMaxConnectionsInput) createMaxConnectionsInput.value = "1";
      lineCreateModal.show();
    });
  }

  // Confirma criação de linha normal (não-teste)
  if (btnLineCreateConfirm) {
    btnLineCreateConfirm.addEventListener("click", () => {
      console.log("[IPTV] Confirmar criação de linha");
      if (!createUsernameInput || !createPasswordInput) return;
      const username = createUsernameInput.value.trim();
      const password = createPasswordInput.value.trim();
      const name = createNameInput ? createNameInput.value.trim() : "";
      const phone = createPhoneInput ? createPhoneInput.value.trim() : "";
      const email = createEmailInput ? createEmailInput.value.trim() : "";

      let months = 1;
      if (createMonthsInput && createMonthsInput.value) {
        const m = parseInt(createMonthsInput.value, 10);
        if (!Number.isNaN(m) && m > 0) {
          months = m;
        }
      }

      const payload = {
        name: name || null,
        username,
        password,
        months,
        max_connections:
          createMaxConnectionsInput && createMaxConnectionsInput.value
            ? parseInt(createMaxConnectionsInput.value, 10)
            : 1,
        is_test: false,
        customer_phone: phone || null,
        customer_email: email || null,
      };

      apiRequest("POST", "/admin/lines/", payload)
        .then(() => {
          if (lineCreateModal) lineCreateModal.hide();
          if (createNameInput) createNameInput.value = "";
          if (createPhoneInput) createPhoneInput.value = "";
          if (createEmailInput) createEmailInput.value = "";
          loadLinesUsers();
          showLineCredentials(username, password, false);
        })
        .catch((err) => showMessageModal("error", "Erro ao criar linha: " + err.message));
    });
  }

  async function loadCurrentUserInfo() {
    if (!accessToken) return;
    try {
      const me = await apiRequest("GET", "/admin/users/me");
      // Info no topo do painel (navbar)
      if (navbarUserInfo) {
        const credits = me.panel_credits ?? 0;
        let panelExp = "-";
        if (me.panel_expires_at) {
          // Espera formato ISO: YYYY-MM-DDTHH:MM[:SS]
          const parts = me.panel_expires_at.split("T");
          if (parts.length >= 2) {
            const [y, m, d] = parts[0].split("-");
            const timeParts = parts[1].split(":");
            const hh = timeParts[0] || "00";
            const mm = timeParts[1] || "00";
            if (y && m && d) {
              panelExp = `${d}/${m}/${y} - ${hh}:${mm}`;
            }
          }
        }

        const roleLabel = (me.role || (me.is_admin ? "admin" : "vendor")).toLowerCase();
        if (roleLabel === "vendor") {
          navbarUserInfo.innerHTML = `
            <span class="badge bg-success me-2">Expiração ${panelExp}</span>
            <span>${me.username}</span>
            <span class="ms-2 fw-semibold">Créditos: ${credits}</span>
          `;
        } else {
          navbarUserInfo.textContent = me.username || currentUsername || "";
        }
      }

      // Para revendedor, apenas exibimos o botão de teste rápido
      if (currentUserRole === "vendor" && btnLineTest3h) {
        btnLineTest3h.classList.remove("d-none");
      }
      if (panelSettingsCard && currentUserRole !== "admin") {
        panelSettingsCard.classList.add("d-none");
      }
    } catch (err) {
      console.warn("Erro ao carregar dados do usuário atual", err);
    }
  }

  let allUserLines = [];
  let allTestLines = [];

  function renderLinesUsers() {
    if (!tableLinesUsersBody) return;
    tableLinesUsersBody.innerHTML = "";
    const query = (linesFilterQuery && linesFilterQuery.value.trim().toLowerCase()) || "";
    const statusFilter = (linesFilterStatus && linesFilterStatus.value) || "all";
    const expiryFilter = (linesFilterExpiry && linesFilterExpiry.value) || "all";

    const now = new Date();

    allUserLines.forEach((ln) => {
      const createdAt = formatIsoDateTime(ln.created_at);
      const expiresAt = formatIsoDateTime(ln.expires_at);

      let isExpired = false;
      if (ln.expires_at) {
        const expDate = new Date(ln.expires_at);
        isExpired = expDate < now;
      }
      const status = isExpired ? "E" : "A";

      // filtros
      if (statusFilter !== "all" && status !== statusFilter) return;
      if (expiryFilter !== "all") {
        if (ln.expires_at) {
          const expDate = new Date(ln.expires_at);
          const isExpired = expDate < now;
          if (expiryFilter === "active" && isExpired) return;
          if (expiryFilter === "expired" && !isExpired) return;
        } else if (expiryFilter !== "all") {
          // sem expiração: considera como ativo
          if (expiryFilter === "expired") return;
        }
      }

      if (query) {
        const hay = `${ln.name || ""} ${ln.username || ""} ${ln.customer_email || ""}`.toLowerCase();
        if (!hay.includes(query)) return;
      }

      const tr = document.createElement("tr");
      tr.innerHTML = `
          <td><input type="checkbox" class="line-select" data-id="${ln.id}"></td>
          <td>${ln.name || "-"}</td>
          <td>${ln.username}</td>
          <td>${ln.password}</td>
          <td>${ln.customer_email || "-"}</td>
          <td>${createdAt}</td>
          <td>${expiresAt}</td>
          <td><span class="status-badge ${status === "A" ? "status-badge-a" : "status-badge-e"}">${status}</span></td>
          <td>${ln.max_connections}</td>
          <td>${ln.owner_id}</td>
          <td class="text-nowrap">
            <button
              class="btn btn-sm btn-primary me-1 btn-line-edit"
              data-id="${ln.id}"
              data-name="${ln.name || ""}"
              data-email="${ln.customer_email || ""}"
              data-phone="${ln.customer_phone || ""}"
              data-active="${ln.is_active ? "1" : "0"}"
              data-maxconn="${ln.max_connections}"
              title="Editar linha"
            ><i class="bi bi-pencil"></i></button>
            <button
              class="btn btn-sm btn-info text-white me-1 btn-line-cred"
              data-username="${ln.username}"
              data-password="${ln.password}"
              title="Ver dados de acesso"
            ><i class="bi bi-key"></i></button>
            <button class="btn btn-sm btn-success me-1 btn-line-m3u" data-username="${ln.username}" data-password="${ln.password}" title="Baixar playlist M3U8">
              <i class="bi bi-download"></i>
            </button>
            <button class="btn btn-sm btn-danger btn-line-del" data-id="${ln.id}" title="Remover linha">
              <i class="bi bi-trash"></i>
            </button>
          </td>
        `;
        tableLinesUsersBody.appendChild(tr);
      });
  }

  function renderLinesTests() {
    if (!tableLinesTestsBody) return;
    tableLinesTestsBody.innerHTML = "";

    const query = (testsFilterQuery && testsFilterQuery.value.trim().toLowerCase()) || "";
    const statusFilter = (testsFilterStatus && testsFilterStatus.value) || "all";
    const expiryFilter = (testsFilterExpiry && testsFilterExpiry.value) || "all";

    const now = new Date();

    allTestLines.forEach((ln) => {
      const expiresAt = formatIsoDateTime(ln.expires_at);

      let isExpired = false;
      if (ln.expires_at) {
        const expDate = new Date(ln.expires_at);
        isExpired = expDate < now;
      }
      const status = isExpired ? "E" : "A";

      if (statusFilter !== "all" && status !== statusFilter) return;
      if (expiryFilter !== "all") {
        if (ln.expires_at) {
          const expDate = new Date(ln.expires_at);
          const isExpired = expDate < now;
          if (expiryFilter === "active" && isExpired) return;
          if (expiryFilter === "expired" && !isExpired) return;
        } else if (expiryFilter !== "all") {
          if (expiryFilter === "expired") return;
        }
      }

      if (query) {
        const hay = `${ln.username || ""}`.toLowerCase();
        if (!hay.includes(query)) return;
      }

      const tr = document.createElement("tr");
      tr.innerHTML = `
          <td><input type="checkbox" class="test-select" data-id="${ln.id}"></td>
          <td>${ln.id}</td>
          <td>${ln.username}</td>
          <td>${ln.password}</td>
          <td>${ln.owner_id}</td>
          <td>${expiresAt}</td>
          <td><span class="status-badge ${status === "A" ? "status-badge-a" : "status-badge-e"}">${status}</span></td>
          <td>${ln.max_connections}</td>
          <td class="text-nowrap">
            <button class="btn btn-sm btn-info text-white me-1 btn-line-cred-test" data-username="${ln.username}" data-password="${ln.password}" title="Ver dados de acesso">
              <i class="bi bi-key"></i>
            </button>
            <button class="btn btn-sm btn-success me-1 btn-test-m3u" data-username="${ln.username}" data-password="${ln.password}" title="Baixar playlist M3U8">
              <i class="bi bi-download"></i>
            </button>
            <button class="btn btn-sm btn-success me-1 btn-line-promote" data-id="${ln.id}" title="Promover para linha">
              <i class="bi bi-arrow-up-circle"></i>
            </button>
            <button class="btn btn-sm btn-danger btn-line-del" data-id="${ln.id}" title="Remover teste">
              <i class="bi bi-trash"></i>
            </button>
          </td>
        `;
        tableLinesTestsBody.appendChild(tr);
      });
  }

  // ===== Filtros de Linhas IPTV =====
  if (linesFilterApply) {
    linesFilterApply.addEventListener("click", () => {
      renderLinesUsers();
    });
  }
  if (linesFilterQuery) {
    linesFilterQuery.addEventListener("keyup", (e) => {
      if (e.key === "Enter") {
        renderLinesUsers();
      }
    });
  }
  if (linesFilterStatus) {
    linesFilterStatus.addEventListener("change", () => {
      renderLinesUsers();
    });
  }
  if (linesFilterExpiry) {
    linesFilterExpiry.addEventListener("change", () => {
      renderLinesUsers();
    });
  }

  // ===== Filtros de Testes IPTV =====
  if (testsFilterApply) {
    testsFilterApply.addEventListener("click", () => {
      renderLinesTests();
    });
  }
  if (testsFilterQuery) {
    testsFilterQuery.addEventListener("keyup", (e) => {
      if (e.key === "Enter") {
        renderLinesTests();
      }
    });
  }
  if (testsFilterStatus) {
    testsFilterStatus.addEventListener("change", () => {
      renderLinesTests();
    });
  }
  if (testsFilterExpiry) {
    testsFilterExpiry.addEventListener("change", () => {
      renderLinesTests();
    });
  }

  async function loadLinesUsers() {
    if (!tableLinesUsersBody || !accessToken) return;
    try {
      const lines = await apiRequest("GET", "/admin/lines/?is_test=false");
      allUserLines = lines;
      renderLinesUsers();

      const modalLineName = document.getElementById("modal-line-name");
      const modalLinePhone = document.getElementById("modal-line-phone");
      const modalLineEmail = document.getElementById("modal-line-email");

      tableLinesUsersBody.querySelectorAll(".btn-line-edit").forEach((btn) => {
        btn.addEventListener("click", () => {
          const id = btn.getAttribute("data-id");
          if (!lineEditModal) return;

          editingLineId = id;

          const name = btn.getAttribute("data-name") || "";
          const email = btn.getAttribute("data-email") || "";
          const phone = btn.getAttribute("data-phone") || "";
          const isActiveFlag = btn.getAttribute("data-active") === "1";
          const maxConnTxt = btn.getAttribute("data-maxconn") || "1";

          if (modalLineName) modalLineName.value = name;
          if (modalLinePhone) modalLinePhone.value = phone;
          if (modalLineEmail) modalLineEmail.value = email;
          if (modalLineActive) modalLineActive.checked = isActiveFlag;
          if (modalLineMonths) modalLineMonths.value = "keep";
          if (modalLineMaxConnections) {
            modalLineMaxConnections.value = maxConnTxt || "1";
          }

          lineEditModal.show();
        });
      });

      tableLinesUsersBody.querySelectorAll(".btn-line-del").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = btn.getAttribute("data-id");
          const ok = await showConfirmDialog("Remover esta linha?", { title: "Remover linha" });
          if (!ok) return;
          apiRequest("DELETE", `/admin/lines/${id}`)
            .then(() => {
              loadLinesUsers();
            })
            .catch((err) => showMessageModal("error", "Erro ao remover linha: " + err.message));
        });
      });

      // Botão para ver dados (credenciais) de cada linha
      tableLinesUsersBody.querySelectorAll(".btn-line-cred").forEach((btn) => {
        btn.addEventListener("click", () => {
          const username = btn.getAttribute("data-username") || "";
          const password = btn.getAttribute("data-password") || "";
          if (!username || !password) return;
          showLineCredentials(username, password, false);
        });
      });

      // Botão para baixar playlist M3U8 de cada linha
      tableLinesUsersBody.querySelectorAll(".btn-line-m3u").forEach((btn) => {
        btn.addEventListener("click", () => {
          const username = btn.getAttribute("data-username") || "";
          const password = btn.getAttribute("data-password") || "";
          if (!username || !password) return;
          const base = baseUrl.replace(/\/$/, "");
          const url = `${base}/get.php?username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}&type=m3u&output=m3u8`;
          const a = document.createElement("a");
          a.href = url;
          a.download = `${username}.m3u8`;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
        });
      });

      // Checkboxes e seleção em lote
      if (linesSelectAll) {
        linesSelectAll.checked = false;
        linesSelectAll.addEventListener("change", () => {
          const checked = linesSelectAll.checked;
          tableLinesUsersBody.querySelectorAll(".line-select").forEach((cb) => {
            cb.checked = checked;
          });
        });
      }
    } catch (err) {
      console.error("Erro ao carregar linhas de usuários", err);
    }
  }

  function getSelectedLineIds() {
    const ids = [];
    if (!tableLinesUsersBody) return ids;
    tableLinesUsersBody.querySelectorAll(".line-select:checked").forEach((cb) => {
      const id = cb.getAttribute("data-id");
      if (id) ids.push(parseInt(id, 10));
    });
    return ids;
  }

  // Seleção múltipla para testes IPTV
  function getSelectedTestIds() {
    const ids = [];
    if (!tableLinesTestsBody) return ids;
    tableLinesTestsBody.querySelectorAll(".test-select:checked").forEach((cb) => {
      const id = cb.getAttribute("data-id");
      if (id) ids.push(parseInt(id, 10));
    });
    return ids;
  }

  if (bulkDeleteLinesBtn) {
    bulkDeleteLinesBtn.addEventListener("click", async () => {
      const ids = getSelectedLineIds();
      if (!ids.length) return;
      const ok = await showConfirmDialog("Excluir as linhas selecionadas?", { title: "Excluir linhas" });
      if (!ok) return;
      apiRequest("POST", "/admin/lines/bulk/delete", ids)
        .then(() => loadLinesUsers())
        .catch((err) => showMessageModal("error", "Erro ao excluir linhas: " + err.message));
    });
  }

  if (bulkRenewLinesBtn) {
    bulkRenewLinesBtn.addEventListener("click", async () => {
      const ids = getSelectedLineIds();
      if (!ids.length) return;
      const ok = await showConfirmDialog("Renovar as linhas selecionadas por +30 dias?", { title: "Renovar linhas" });
      if (!ok) return;
      apiRequest("POST", "/admin/lines/bulk/renew?months=1", ids)
        .then(() => loadLinesUsers())
        .catch((err) => showMessageModal("error", "Erro ao renovar linhas: " + err.message));
    });
  }

  if (bulkChangeOwnerLinesBtn) {
    bulkChangeOwnerLinesBtn.addEventListener("click", () => {
      const ids = getSelectedLineIds();
      if (!ids.length) return;
      const newOwnerId = prompt("ID do novo revendedor (owner_id):");
      if (!newOwnerId) return;
      const payload = {
        ids,
        new_owner_id: parseInt(newOwnerId, 10),
      };
      apiRequest("POST", "/admin/lines/bulk/change-owner", payload)
        .then(() => loadLinesUsers())
        .catch((err) => showMessageModal("error", "Erro ao alterar revenda: " + err.message));
    });
  }

  if (bulkDeleteTestsBtn) {
    bulkDeleteTestsBtn.addEventListener("click", async () => {
      const ids = getSelectedTestIds();
      if (!ids.length) return;
      const ok = await showConfirmDialog("Excluir os testes selecionados?", { title: "Excluir testes" });
      if (!ok) return;

      for (const id of ids) {
        try {
          await apiRequest("DELETE", `/admin/lines/${id}`);
        } catch (err) {
          console.error("Erro ao excluir teste", id, err);
        }
      }
      loadLinesTests();
    });
  }

  if (bulkPromoteTestsBtn) {
    bulkPromoteTestsBtn.addEventListener("click", async () => {
      const ids = getSelectedTestIds();
      if (!ids.length) return;
      const ok = await showConfirmDialog("Promover os testes selecionados para linhas?", { title: "Promover testes" });
      if (!ok) return;

      for (const id of ids) {
        try {
          await apiRequest("POST", `/admin/lines/${id}/promote`);
        } catch (err) {
          console.error("Erro ao promover teste", id, err);
        }
      }

      loadLinesUsers();
      loadLinesTests();
    });
  }

  async function loadLinesTests() {
    if (!tableLinesTestsBody || !accessToken) return;
    try {
      const lines = await apiRequest("GET", "/admin/lines/?is_test=true");
      allTestLines = lines;

      renderLinesTests();

      tableLinesTestsBody.querySelectorAll(".btn-line-promote").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = btn.getAttribute("data-id");
          const ok = await showConfirmDialog("Promover este teste para uma linha definitiva?", {
            title: "Promover teste",
          });
          if (!ok) return;

          apiRequest("POST", `/admin/lines/${id}/promote`)
            .then(() => {
              loadLinesUsers();
              loadLinesTests();
            })
            .catch((err) => showMessageModal("error", "Erro ao promover teste: " + err.message));
        });
      });

      tableLinesTestsBody.querySelectorAll(".btn-line-del").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = btn.getAttribute("data-id");
          const ok = await showConfirmDialog("Remover este teste?", { title: "Remover teste" });
          if (!ok) return;
          apiRequest("DELETE", `/admin/lines/${id}`)
            .then(() => {
              loadLinesTests();
            })
            .catch((err) => showMessageModal("error", "Erro ao remover teste: " + err.message));
        });
      });

      // Botão para ver dados (credenciais) de cada teste
      tableLinesTestsBody.querySelectorAll(".btn-line-cred-test").forEach((btn) => {
        btn.addEventListener("click", () => {
          const username = btn.getAttribute("data-username") || "";
          const password = btn.getAttribute("data-password") || "";
          if (!username || !password) return;
          showLineCredentials(username, password, true);
        });
      });
      // Botão para baixar playlist M3U8 dos testes
      tableLinesTestsBody.querySelectorAll(".btn-test-m3u").forEach((btn) => {
        btn.addEventListener("click", () => {
          const username = btn.getAttribute("data-username") || "";
          const password = btn.getAttribute("data-password") || "";
          if (!username || !password) return;
          const base = baseUrl.replace(/\/$/, "");
          const url = `${base}/get.php?username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}&type=m3u&output=m3u8`;
          const a = document.createElement("a");
          a.href = url;
          a.download = `${username}.m3u8`;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
        });
      });
      if (testsSelectAll) {
        testsSelectAll.checked = false;
        testsSelectAll.addEventListener("change", () => {
          const checked = testsSelectAll.checked;
          tableLinesTestsBody.querySelectorAll(".test-select").forEach((cb) => {
            cb.checked = checked;
          });
        });
      }
    } catch (err) {
      console.error("Erro ao carregar testes IPTV", err);
    }
  }

  // Helper para carregar todas as listas de linhas (usuários finais e testes)
  async function loadLines() {
    await Promise.allSettled([loadLinesUsers(), loadLinesTests()]);
  }

  // Restaura sessão a partir do token salvo, se possível
  (async function restoreSession() {
    let stored = null;
    try {
      stored = localStorage.getItem("xtream_panel_token");
    } catch (_) {
      stored = null;
    }
    if (!stored) return;

    accessToken = stored;
    try {
      const payload = parseJwt(accessToken);
      currentUserRole = (payload.role || (payload.is_admin ? "admin" : "vendor") || "admin").toLowerCase();
      currentUserId = payload.sub || payload.user_id || null;
      currentUsername = payload.sub || null;

      if (currentUserRole === "vendor" && lineOwnerWrapper) {
        lineOwnerWrapper.style.display = "none";
      }

      sectionLogin.classList.add("hidden");
      adminWrapper.classList.remove("hidden");

      // Determina a seção inicial com base na última usada, respeitando permissões
      let lastSection = null;
      try {
        lastSection = localStorage.getItem("xtream_panel_section");
      } catch (_) {
        lastSection = null;
      }

      if (currentUserRole === "admin") {
        const allowed = ["dashboard", "users", "lines", "tests", "categories", "channels", "vod", "settings"];
        const initial = allowed.includes(lastSection) ? lastSection : "dashboard";
        showSection(initial);
        if (initial === "users") {
          loadUsers();
        }
      } else {
        // vendor: esconde seções somente de admin
        resetNavVisibility();
        document
          .querySelectorAll(
            '[data-section="dashboard"], [data-section="users"], [data-section="categories"], [data-section="channels"], [data-section="vod"], [data-section="settings"]'
          )
          .forEach((el) => {
            const li = el.closest("li");
            if (li) li.style.display = "none";
          });

        const allowedVendor = ["lines", "tests"]; // sections liberadas para revendedor
        const initialVendor = allowedVendor.includes(lastSection) ? lastSection : "lines";
        showSection(initialVendor);

        // Mostra blocos de filtros do layout de vendedor
        document.querySelectorAll(".vendor-filters").forEach((el) => {
          el.classList.remove("d-none");
        });
      }

      await Promise.all([loadLines(), loadCurrentUserInfo(), loadPanelSettings()]);
    } catch (err) {
      // token inválido, limpa e volta ao login
      accessToken = null;
      try {
        localStorage.removeItem("xtream_panel_token");
      } catch (_) {}
      sectionLogin.classList.remove("hidden");
      adminWrapper.classList.add("hidden");
    }
  })();

  // Não usamos mais submit direto do formLine; criação é feita via modal lineCreateModal

  if (btnLineSave) {
    btnLineSave.addEventListener("click", () => {
      if (!editingLineId) return;

      const modalLineName = document.getElementById("modal-line-name");
      const modalLinePhone = document.getElementById("modal-line-phone");
      const modalLineEmail = document.getElementById("modal-line-email");

      const payload = {};

      if (modalLineName) {
        const name = modalLineName.value.trim();
        payload.name = name || null;
      }
      if (modalLinePhone) {
        const phone = modalLinePhone.value.trim();
        payload.customer_phone = phone || null;
      }
      if (modalLineEmail) {
        const email = modalLineEmail.value.trim();
        payload.customer_email = email || null;
      }

      if (modalLineActive) payload.is_active = !!modalLineActive.checked;

      // senha não é mais editável; não enviamos password no update
      if (modalLineMonths) {
        const choice = modalLineMonths.value;
        if (choice === "clear") {
          payload.expires_at = null;
        } else if (choice !== "keep") {
          const months = parseInt(choice, 10);
          if (!Number.isNaN(months) && months > 0) {
            // Enviamos meses para o backend calcular a nova expiração e debitar créditos
            payload.months = months;
          }
        }
      }

      if (modalLineMaxConnections && modalLineMaxConnections.value) {
        payload.max_connections = parseInt(modalLineMaxConnections.value, 10);
      }

      apiRequest("PATCH", `/admin/lines/${editingLineId}`, payload)
        .then(() => {
          if (lineEditModal) lineEditModal.hide();
          editingLineId = null;
          loadLinesUsers();
        })
        .catch((err) => showMessageModal("error", "Erro ao atualizar linha: " + err.message));
    });
  }

  function generateRandomId(length) {
    const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    let out = "";
    for (let i = 0; i < length; i++) {
      out += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return out;
  }

  function showMessageModal(type, message) {
    if (!messageModal) {
      // fallback
      window.alert(message);
      return;
    }
    // Garante que não haja outro modal aberto "por cima" (como criação/edição de linha)
    try {
      if (lineCreateModalEl && lineCreateModalEl.classList.contains("show") && lineCreateModal) {
        lineCreateModal.hide();
      }
      if (lineEditModalEl && lineEditModalEl.classList.contains("show") && lineEditModal) {
        lineEditModal.hide();
      }
      if (lineTestModalEl && lineTestModalEl.classList.contains("show") && lineTestModal) {
        lineTestModal.hide();
      }
    } catch (_) {}

    const isError = type === "error";
    if (messageModalTitle) {
      messageModalTitle.textContent = isError ? "Erro" : "Aviso";
    }
    if (messageModalBody) {
      messageModalBody.textContent = message;
    }
    messageModal.show();
  }

  function showConfirmDialog(message, options) {
    return new Promise((resolve) => {
      if (!confirmModal) {
        const ok = window.confirm(message);
        resolve(ok);
        return;
      }

      const title = (options && options.title) || "Confirmação";
      if (confirmModalTitle) confirmModalTitle.textContent = title;
      if (confirmModalBody) confirmModalBody.textContent = message;

      const handlerOk = () => {
        confirmModalOk.removeEventListener("click", handlerOk);
        confirmModalEl.removeEventListener("hidden.bs.modal", handlerCancel);
        resolve(true);
      };
      const handlerCancel = () => {
        confirmModalOk.removeEventListener("click", handlerOk);
        confirmModalEl.removeEventListener("hidden.bs.modal", handlerCancel);
        resolve(false);
      };

      if (confirmModalOk) confirmModalOk.addEventListener("click", handlerOk);
      if (confirmModalEl) confirmModalEl.addEventListener("hidden.bs.modal", handlerCancel, { once: true });

      confirmModal.show();
    });
  }

  if (btnMessageCopy && messageModalBody) {
    btnMessageCopy.addEventListener("click", async () => {
      const text = messageModalBody.textContent || "";
      if (!text) return;
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(text);
        } else {
          const ta = document.createElement("textarea");
          ta.value = text;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand("copy");
          document.body.removeChild(ta);
        }
        const original = btnMessageCopy.textContent;
        btnMessageCopy.textContent = "Copiado";
        setTimeout(() => {
          btnMessageCopy.textContent = original;
        }, 2000);
      } catch (err) {
        console.error("Falha ao copiar texto", err);
        // Fallback extra para navegadores móveis que bloqueiam APIs de clipboard:
        // exibe um prompt nativo com o texto para o usuário copiar manualmente.
        try {
          window.prompt("Copie os dados abaixo:", text);
        } catch (_) {
          // se até o prompt falhar, não há muito o que fazer além de exibir o texto no modal
        }
      }
    });
  }

  function showLineCredentials(username, password, isTest) {
    const panelLabel = (panelNameEl && panelNameEl.textContent) || "Xtream Python";
    const base = baseUrl.replace(/\/$/, "");

    const m3uTs = `${base}/get.php?username=${username}&password=${password}&type=m3u_plus&output=mpegts`;
    const m3uHls = `${base}/get.php?username=${username}&password=${password}&type=m3u_plus&output=hls`;

    const header = `Seja bem vindo a ${panelLabel}`;
    let body =
      `${header}\n\n` +
      "====================================\n\n" +
      "CELULARES, TABLETS, TV BOX e demais apps (iOS ou ANDROID)\n" +
      "╭─ 📱\n" +
      "├●   🟢 Preencha todos os dados corretamente\n" +
      "├●\n" +
      `├●   📡 DNS / URL: ${base}\n` +
      `├●   👤 USUÁRIO: ${username}\n` +
      `├●   🔐 SENHA:  ${password}\n` +
      "╰──> Obs: Caso não entre, verifique se digitou tudo corretamente.\n\n" +
      "LISTAS M3U (SMART TV, IPTV SMARTERS, IBO PLAYER, DUPLECAST, ETC.)\n\n" +
      "🟢 Link (M3U MPEGTS):\n" +
      `${m3uTs}\n\n` +
      "🟡 Link (M3U HLS):\n" +
      `${m3uHls}`;

    if (isTest) {
      body += "\n\nEste acesso é um TESTE temporário.\n";
    }

    showMessageModal("info", body);
  }

  function formatIsoDateTime(iso) {
    if (!iso) return "-";
    try {
      const parts = String(iso).split("T");
      if (parts.length < 2) return iso;
      const [y, m, d] = parts[0].split("-");
      const timeParts = parts[1].split(":");
      const hh = timeParts[0] || "00";
      const mm = timeParts[1] || "00";
      if (!y || !m || !d) return iso;
      return `${d}/${m}/${y} - ${hh}:${mm}`;
    } catch (_) {
      return iso;
    }
  }

  if (btnLineTest3h) {
    btnLineTest3h.addEventListener("click", () => {
      if (!lineTestModal || !testUsernameInput || !testPasswordInput) return;
      const username = generateRandomId(6);
      const password = generateRandomId(6);
      testUsernameInput.value = username;
      testPasswordInput.value = password;
      lineTestModal.show();
    });
  }

  if (btnLineTestConfirm) {
    btnLineTestConfirm.addEventListener("click", () => {
      if (!testUsernameInput || !testPasswordInput) return;
      const username = testUsernameInput.value;
      const password = testPasswordInput.value;
      if (!username || !password) return;

      const threeHoursMs = 3 * 60 * 60 * 1000;
      const exp = new Date(Date.now() + threeHoursMs);
      const iso = exp.toISOString().slice(0, 16);

      const payload = {
        username,
        password,
        expires_at: iso,
        max_connections: 1,
        is_test: true,
      };

      apiRequest("POST", "/admin/lines/", payload)
        .then(() => {
          if (lineTestModal) lineTestModal.hide();
          loadLinesTests();
          showLineCredentials(username, password, true);
        })
        .catch((err) => showMessageModal("error", "Erro ao criar teste: " + err.message));
    });
  }

  if (formPanelSettings) {
    formPanelSettings.addEventListener("submit", (e) => {
      e.preventDefault();
      if (!accessToken || currentUserRole !== "admin") {
        showMessageModal("error", "Apenas administradores podem alterar as configurações do painel.");
        return;
      }

      // Guarda os temas atuais antes de salvar, para detectar mudança
      const previousLoginTheme = inputLoginTheme ? inputLoginTheme.value : null;
      const previousPanelTheme = inputPanelTheme ? inputPanelTheme.value : null;

      const payload = {
        panel_name: inputPanelName ? inputPanelName.value : "",
        server_message: inputServerMessage ? inputServerMessage.value : "",
        timezone: inputTimezone ? inputTimezone.value : undefined,
        login_theme: inputLoginTheme ? inputLoginTheme.value : undefined,
        panel_theme: inputPanelTheme ? inputPanelTheme.value : undefined,
      };

      apiRequest("PUT", "/admin/settings/", payload)
        .then((data) => {
          if (panelNameEl && data.panel_name) {
            panelNameEl.textContent = data.panel_name;
          }
          if (data.panel_name) {
            document.title = `${data.panel_name} - Painel Xtream`;
          }
          if (serverMessageBox && serverMessageText) {
            const msg = data.server_message || "";
            if (msg) {
              serverMessageText.textContent = msg;
              serverMessageBox.classList.remove("d-none");
            } else {
              serverMessageText.textContent = "";
              serverMessageBox.classList.add("d-none");
            }
          }

          // Atualiza selects e aplica tema/logo imediatamente após salvar
          if (inputTimezone && data.timezone) {
            inputTimezone.value = data.timezone;
          }
          if (inputLoginTheme && data.login_theme) {
            inputLoginTheme.value = data.login_theme;
            applyLoginTheme(data.login_theme);
          }

          if (inputPanelTheme && data.panel_theme) {
            inputPanelTheme.value = data.panel_theme;
            applyPanelTheme(data.panel_theme);
          }

          const panelLabel = data.panel_name || "Painel";
          showMessageModal(
            "info",
            `Configurações do painel "${panelLabel}" foram salvas com sucesso.`,
          );

          // Se o tema de login ou do painel mudou, recarrega a página para aplicar tudo desde o início
          const loginThemeChanged = previousLoginTheme && data.login_theme && data.login_theme !== previousLoginTheme;
          const panelThemeChanged = previousPanelTheme && data.panel_theme && data.panel_theme !== previousPanelTheme;
          if (loginThemeChanged || panelThemeChanged) {
            setTimeout(() => {
              window.location.reload();
            }, 400);
          }
        })
        .catch((err) => {
          showMessageModal("error", "Erro ao salvar configurações do painel: " + err.message);
        });
    });
  }
})();
