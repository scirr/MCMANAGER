# mc_lang.py — All user-facing strings for MC Manager (FR / EN)
# The active language is chosen at runtime (persisted in language.txt next to
# the app) and can be changed with `mc language fr|en`. A single build ships
# both languages.
import os

# Single source of truth for the tool version (shown by `mc version`).
# Keep identical to Windows/mc_lang.py.
VERSION = "2.4.6"

_LANG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "language.txt")


def _read_saved_language():
    """Return the persisted language ('fr'/'en') or None if not chosen yet."""
    try:
        with open(_LANG_FILE, "r", encoding="utf-8") as f:
            value = f.read().strip().lower()
        return value if value in ("fr", "en") else None
    except Exception:
        return None


def is_language_set():
    return _read_saved_language() is not None


def current_language():
    return _LANG

_FR = {
    # ── icons (mc_deploy.pr, reused by mc_doctor) ────────────────────────────
    "icon_info": "INFO",
    "icon_ok":   "OK",
    "icon_warn": "!",
    "icon_err":  "ERREUR",

    # ── yn prompts ────────────────────────────────────────────────────────────
    "yn_yes":    "[O/n]",
    "yn_no":     "[o/N]",
    "word_default": "défaut",

    # ── mc_setup ──────────────────────────────────────────────────────────────
    "java_required": "Java est requis pour lancer le serveur Minecraft.",
    "java_download": "Téléchargez Java 21 sur : https://adoptium.net/ (ou : sudo dnf install java-21-openjdk-headless)",
    "java_missing":  "Dépendance manquante : java",

    # ── mc_servers ────────────────────────────────────────────────────────────
    "no_server_configured": "Aucun serveur configuré. Lancez \033[96mmc deploy\033[0m pour en créer un.",
    "no_active_server":     "Aucun serveur actif. Choisissez-en un avec \033[96mmc use <nom/numéro>\033[0m (disponibles : {avail}).",
    "server_not_found":     "Serveur '{target}' introuvable. Disponibles : {avail}",
    "server_dir_gone":      "Le dossier du serveur '{name}' n'existe plus : {path}",
    "check_path_or_use":    "Vérifiez le chemin ou choisissez un autre serveur avec : mc use <nom/numéro>",
    "legacy_migrated":      "Configuration existante migrée vers le serveur '{name}' ({path}).",

    # ── mc_core ───────────────────────────────────────────────────────────────
    "already_online":       "Déjà en ligne.",
    "invalid_dir":          "Dossier invalide : {path}",
    "java_not_found_start": "Java est introuvable ou non accessible. Installez Java 21+ : https://adoptium.net/",
    "server_launched":      "Lancé sur {ip} (PID: {pid})",
    "start_console_hint":   "Le serveur tourne en arrière-plan. Tapez 'mc console' pour accéder à sa console.",
    "start_crashed":        "Le serveur s'est arrêté immédiatement après le lancement (port occupé ? JAR corrompu ?). Consultez : {log}",
    "start_port_busy":      "Le port {port} est déjà utilisé : un serveur tourne probablement encore. Démarrage annulé pour éviter un doublon (monde verrouillé). Utilisez 'mc stop --force' si le processus est bloqué.",
    "already_offline":      "Déjà éteint.",
    "stop_sent":            "Arrêt envoyé.",
    "stop_rcon_unreachable": "RCON injoignable : impossible d'envoyer la commande d'arrêt. Le serveur tourne toujours — utilisez « mc stop --force » pour le tuer.",
    "launch_error":         "Erreur lancement : {e}",
    "maintenance_active":   "Mode maintenance actif.",
    "no_webhook":           "Pas de Webhook configuré.",
    "webhook_error":        "Erreur Webhook : {e}",
    "no_world_found":       "Aucun dossier de monde trouvé.",
    "invalid_paths":        "Chemins invalides.",
    "backup_ok":            "Backup {btype} OK.",
    "backup_error":         "Erreur backup : {e}",

    # ── mc_cli — RCON console ─────────────────────────────────────────────────
    "console_offline":      "Le serveur est éteint.",
    "console_connected":    "[CONSOLE] Connecté. Tapez 'exit' ou Ctrl+C pour quitter.",
    "console_hint":         "[INFO] Les commandes sont envoyées via RCON.",
    "console_log_only":     "[INFO] Mode lecture seule — RCON indisponible, commandes désactivées.",
    "console_rcon_error":   "RCON indisponible : {msg}",
    "console_disconnect":   "Déconnexion.",
    "console_error":        "Erreur console : {e}",

    # ── mc_cli — dashboard ────────────────────────────────────────────────────
    "no_server_dashboard":  "Pas de serveur sur cette machine. Lancez 'mc deploy' pour en créer un (ou 'mc help' pour voir toutes les commandes).",
    "active_marker":        "ACTIF",
    "dir_missing":          "DOSSIER INTROUVABLE",
    "status_online":        "EN LIGNE (PID {pid})",
    "status_online_nopid":  "EN LIGNE",
    "status_offline":       "HORS LIGNE",
    "mode_schedule":        "Horaires",
    "mode_always_on":       "24h/24",
    "mode_maintenance":     "Maintenance",
    "mode_sched_hours":     "Horaires ({oh:02d}:{om:02d} - {ch:02d}:{cm:02d})",
    "mode_maint_was":       "Maintenance (était : {was})",
    "field_status":         "Statut",
    "field_mode":           "Mode",
    "field_version":        "Version",
    "field_dir":            "Dossier",
    "field_port":           "Port",
    "cheatsheet": (
        "\033[96mCommandes principales :\033[0m\n"
        "  mc deploy              Déployer un nouveau serveur\n"
        "  mc use <nom/numéro>    Changer le serveur actif\n"
        "  mc start / mc stop     Démarrer / arrêter le serveur actif\n"
        "  mc mode <valeur>       schedule | always-on | maintenance\n"
        "  mc resume              Sortir de maintenance\n"
        "  mc console             Console RCON du serveur actif\n"
        "  mc help                Liste complète des commandes"
    ),
    "no_log_file":          "Aucun fichier daemon.log trouvé.",

    # ── mc_cli — server management ────────────────────────────────────────────
    "target_info":           "Cible : {name} ({sid})",
    "set_active_ok":         "Serveur actif : {name} ({sid})",
    "server_not_found_use":  "Serveur '{target}' introuvable.",
    "deregister_warning":    "Vous allez désinscrire '{name}' (id {sid}).",
    "folder_preserved_info": "Dossier (conservé, non touché) : {path}",
    "confirm_deregister":    "Confirmer la désinscription ?",
    "deregister_cancelled":  "Annulé.",
    "deregister_ok":         "Serveur '{name}' désinscrit du registre.",
    "files_preserved":       "Fichiers conservés : {path}",
    "new_active":            "Nouveau serveur actif : {name}",
    "no_server_left":        "Plus aucun serveur enregistré. Lancez 'mc deploy' ou 'mc add'.",
    "folder_opened":         "Ouvert : {path}",
    "maintenance_activated": "Maintenance activée. Tapez 'mc resume' pour redémarrer.",
    "mode_set":              "Mode : {mode}",
    "maintenance_disabled":  "Maintenance désactivée. Mode actuel : {mode}",
    "schedule_updated":      "Horaires mis à jour, mode passé sur 'schedule'.",

    # ── mc_cli — daemon ───────────────────────────────────────────────────────
    "daemon_launching":      "Lancement du daemon en premier plan...",
    "daemon_ok":             "Daemon {label}.",
    "daemon_not_installed":  "Le service mc_manager n'est pas installé. Relancez install.sh.",
    "daemon_no_perms":       "Impossible de {action} le daemon : droits root requis (relancez avec sudo).",
    "daemon_error_msg":      "Erreur : impossible de {action} le daemon (code {code}). {detail}",
    "daemon_label_started":  "démarré",
    "daemon_label_stopped":  "arrêté",
    "daemon_label_restarted":"redémarré",

    # ── mc_config — smart_ask ─────────────────────────────────────────────────
    "hint_current":          "[Actuel: {val} | RESET pour défaut: {default}]",
    "hint_default":          "[Défaut: {val}]",
    "enter_valid_number":    "Veuillez entrer un nombre valide.",

    # ── mc_config — section headers ───────────────────────────────────────────
    "setup_header":          "Configuration de MC Manager Linux",
    "section_base":          "1. Configuration de Base",
    "section_schedule":      "2. Horaires & Sauvegardes",
    "section_performance":   "Paramètres de Performance (Avancé)",
    "section_integrations":  "3. Intégrations (Optionnel)",
    "section_prereq":        "Vérification des prérequis MCManager",
    "section_firewall":      "Pare-feu (firewalld)",

    # ── mc_config — prompts ───────────────────────────────────────────────────
    "prompt_server_name":    "Nom du serveur",
    "prompt_motd":           "Description MOTD",
    "prompt_dir":            "Dossier du serveur",
    "prompt_backup_dir":     "Dossier des backups",
    "prompt_port":           "Port d'accès au serveur",
    "prompt_always_on":      "Serveur 24h/24 (1=Oui, 0=Non)",
    "prompt_open_hour":      "Heure d'ouverture",
    "prompt_open_min":       "Minute d'ouverture",
    "prompt_close_hour":     "Heure de fermeture",
    "prompt_close_min":      "Minute de fermeture",
    "prompt_cpu":            "Assignation CPU (ex: 8-15)",
    "prompt_ram":            "RAM allouée (ex: 4G, 8G, 4096M)",
    "prompt_jar":            "Fichier JAR exécutable",
    "prompt_domain":         "Domaine / lien du serveur (optionnel)",
    "prompt_webhook_url":    "URL Webhook Discord",
    "prompt_automodpack":    "Activer AutoModpack (0=Non, 1=Oui)",

    # ── mc_config — status messages ───────────────────────────────────────────
    "cpu_info":              "-> Info CPU : {count} cœurs détectés.",
    "cpu_format_hint":       "-> Format affinité : '8-15' (plage), '0,1,2' (liste), '0-7' (8 premiers)",
    "rcon_already_ok":       "RCON déjà configuré.",
    "rcon_not_configured":   "RCON n'est pas configuré sur ce serveur (obligatoire pour MC Manager : arrêt propre, console, sauvegardes, avertissements).",
    "firewall_ok":           "Port {port} (TCP) ouvert dans firewalld.",
    "firewall_failed":       "Port non ouvert automatiquement (firewalld inactif, ou droits root requis ?).",
    "firewall_manual_hint":  "Pour autoriser ce serveur manuellement, lancez :",
    "automod_fp_detected":   "Clé AutoModpack détectée automatiquement : {fp}",
    "automod_fp_pending":    "Clé AutoModpack pas encore disponible (sera détectée automatiquement au prochain 'mc start').",
    "setup_success":         "Fichier config mis à jour.",
    "webhooks_edit_hint":    "Éditez 'webhooks.json' (dans le dossier du serveur) pour personnaliser les messages Discord.",

    # ── mc_config — mc command / systemd install ─────────────────────────────
    "install_mc_header":      "Installation de la commande globale",
    "install_mc_ok":          "Commande 'mc' installée dans /usr/local/bin !",
    "install_mc_new_term":    "Ouvrez un nouveau terminal pour utiliser 'mc'.",
    "install_mc_perms":       "Droits root nécessaires pour écrire dans /usr/local/bin.",
    "install_mc_manual":      "Copiez manuellement : {src} -> {dst}",
    "daemon_inst_header":     "Installation du Daemon (service systemd)",
    "daemon_inst_ok":         "Service '{name}' installé et démarré !",
    "daemon_inst_silent":     "Tourne en arrière-plan. Démarre automatiquement avec le système.",
    "daemon_inst_failed":     "Impossible de démarrer le service.",
    "daemon_inst_rerun":      "Relancez avec sudo.",

    # ── mc_deploy — shared ────────────────────────────────────────────────────
    "deploy_header":          "Déploiement de serveur — MC Manager",
    "add_header":             "Ajout d'un serveur existant — MC Manager",
    "prompt_install_dir":     "Dossier d'installation du serveur",
    "dir_has_server":         "Le dossier '{path}' contient déjà un serveur !",
    "dir_has_server_cont":    "Continuer quand même ? (risque d'écrasement)",
    "deploy_cancelled":       "Déploiement annulé.",
    "add_cancelled":          "Ajout annulé.",
    "server_type_header":     "Type de serveur :",
    "choice":                 "Choix",
    "invalid_choice":         "Choix invalide.",
    "java_not_found_forge":   "Java est introuvable ou non accessible.",
    "java_needed_forge":      "Installez Java 21+ avant de déployer Forge ou NeoForge.",
    "java_detected":          "Java détecté : {ver}",
    "port_conflict_deploy":   "Le port {port} est déjà utilisé par le serveur '{name}'. Choisissez-en un autre.",
    "summary":                "Récapitulatif :",
    "summary_name":           "Nom      : {name}",
    "summary_type":           "Type     : {stype}",
    "summary_version":        "Version  : {ver}",
    "summary_port":           "Port     : {port}",
    "summary_dir":            "Dossier  : {path}",
    "confirm_deploy":         "Confirmer le déploiement ?",
    "deploy_failed_dl":       "Échec du déploiement. Vérifiez votre connexion et la version choisie.",
    "jar_run_bat":            "{stype} installé — démarrage via {script}.",
    "jar_main":               "JAR principal : {jar}",
    "deploy_success":         "Serveur {stype} {ver} déployé avec succès !",
    "deploy_dir_info":        "Dossier serveur : {path}",
    "advanced_prompt":        "Configurer les options avancées maintenant (horaires, CPU/RAM, domaine, Discord) ?",
    "advanced_saved":         "Configuration avancée enregistrée.",
    "later_hint":             "Vous pourrez les régler plus tard avec : mc configure",
    "start_hint":             "Lancez le serveur : mc start",

    # mc add
    "add_dir_prompt":         "Dossier du serveur existant",
    "add_dir_not_exists":     "Le dossier '{path}' n'existe pas.",
    "add_not_a_server":       "'{path}' ne ressemble pas à un serveur Minecraft (pas de .jar/eula.txt/server.properties trouvé).",
    "add_continue_anyway":    "Continuer quand même ?",
    "add_jar_prompt":         "Fichier JAR exécutable",
    "add_detected":           "Détecté : {loader} {ver}",
    "add_not_detected":       "Loader/version non détectés automatiquement (sans impact, modifiable avec : mc edit config).",
    "add_port_conflict":      "Le port {port} est déjà utilisé par le serveur '{name}'. Choisissez-en un autre.",
    "add_registered_ok":      "Serveur '{name}' enregistré.",

    # RCON setup
    "rcon_step":              "Configuration RCON",
    "rcon_pass_prompt":       "Mot de passe RCON",
    "rcon_port_prompt":       "Port RCON",
    "rcon_port_conflict":     "Le port RCON {port} est déjà utilisé par le serveur '{name}'. Choisissez-en un autre.",
    "rcon_configured_ok":     "RCON configuré sur le port {port}.",

    # AutoModpack setup
    "config_loaded":          "Configuration existante trouvée et chargée depuis config.json :",
    "config_field_loaded":    "  {label} : {val}",
    "config_nothing_missing": "Tous les champs essentiels sont déjà configurés.",
    "review_config_prompt":   "Voulez-vous revoir la configuration complète du serveur (horaires, CPU/RAM, Discord...) ?",
    "automod_already":        "AutoModpack déjà présent dans le dossier mods — rien à installer.",
    "automod_checking":       "Vérification de la disponibilité d'AutoModpack",
    "automod_no_loader":      "AutoModpack n'est pas disponible pour un serveur {loader} (nécessite un mod loader : Fabric, Forge ou NeoForge).",
    "automod_unavail":        "AutoModpack n'est pas disponible pour Minecraft {ver} avec le loader {loader}.",
    "automod_avail":          "AutoModpack {aver} disponible pour {loader} {ver}.",
    "automod_desc":           "AutoModpack synchronise automatiquement les mods/resource packs du serveur vers chaque joueur qui se connecte (plus besoin d'installer les mods à la main). Optionnel : sans lui, les joueurs devront installer eux-mêmes les mêmes mods que le serveur.",
    "automod_prompt":         "Installer AutoModpack ?",
    "automod_key_found":      "Clé AutoModpack détectée : {fp}",
    "automod_key_later":      "Clé AutoModpack : sera détectée automatiquement au premier 'mc start'.",
    "automod_installed":      "AutoModpack installé dans {path}/",

    # downloads / API
    "downloading":            "Téléchargement{label} ...",
    "download_failed":        "Échec téléchargement : {e}",
    "api_error":              "Impossible de contacter l'API : {e}",
    "checksum_verified":      "Intégrité du fichier vérifiée ({algo}).",
    "checksum_failed":        "Échec de vérification d'intégrité pour {file} (téléchargement corrompu ?) — fichier supprimé, réessayez.",
    "eula_accepted":          "eula.txt accepté automatiquement.",
    "server_props_gen":       "server.properties généré (port, motd, rcon, gamemode...).",

    # version picker
    "versions_fetching":      "Récupération des versions Minecraft ...",
    "versions_header":        "Versions disponibles (15 dernières releases) :",
    "version_prompt":         "Numéro ou version exacte",

    # server type steps
    "step_vanilla":           "Déploiement Vanilla",
    "step_paper":             "Déploiement Paper",
    "step_fabric":            "Déploiement Fabric",
    "step_forge":             "Déploiement Forge",
    "step_neoforge":          "Déploiement NeoForge",
    "version_not_found":      "Version {ver} introuvable.",
    "paper_not_available":    "Paper non disponible pour {ver}.",
    "no_forge_versions":      "Aucune version Forge trouvée pour {ver}.",
    "forge_selected":         "Version Forge sélectionnée : {ver}",
    "forge_installing":       "Installation Forge (peut prendre quelques minutes) ...",
    "forge_failed":           "L'installer Forge a échoué.",
    "forge_timeout":          "Timeout pendant l'installation Forge.",
    "forge_installer_del":    "Installer Forge supprimé.",
    "forge_ok":               "Forge installé — démarrage via run.sh.",
    "neoforge_not_available": "NeoForge non disponible pour {ver}.",
    "neoforge_installing":    "Installation NeoForge ...",
    "neoforge_failed":        "L'installer NeoForge a échoué.",
    "neoforge_timeout":       "Timeout pendant l'installation NeoForge.",
    "neoforge_installer_del": "Installer NeoForge supprimé.",
    "neoforge_ok":            "NeoForge installé — démarrage via run.sh.",

    # ── mc_doctor ─────────────────────────────────────────────────────────────
    "no_server_cfg_doctor":   "Aucun serveur configuré. Lancez mc deploy.",
    "doctor_label_dir":       "Dossier serveur",
    "doctor_dir_fix":         "mc configure {name}  # ou vérifiez que le chemin existe",
    "doctor_label_java":      "Java",
    "doctor_java_fix":        "Installez Java 21+ : https://adoptium.net/ (ou : sudo dnf install java-21-openjdk-headless)",
    "doctor_label_rcon_cfg":  "RCON configuré",
    "doctor_rcon_cfg_ok":     "mot de passe RCON présent",
    "doctor_rcon_cfg_miss":   "manquant",
    "doctor_rcon_cfg_fix":    "mc configure {name}",
    "doctor_label_rcon_live": "RCON joignable",
    "doctor_rcon_offline":    "serveur hors ligne, non testé",
    "doctor_rcon_live_fix":   "Vérifiez enable-rcon=true dans server.properties, ou redémarrez le serveur.",
    "doctor_label_firewall":  "Pare-feu (port jeu)",
    "doctor_fw_present":      "port '{rule}' ouvert",
    "doctor_fw_absent":       "fermé",
    "doctor_fw_no_firewalld": "firewalld indisponible (non installé ou inactif)",
    "doctor_label_service":   "Service mc_manager",
    "doctor_svc_running":     "en cours d'exécution",
    "doctor_svc_stopped":     "installé mais arrêté",
    "doctor_svc_not_inst":    "service non installé",
    "doctor_svc_no_sc":       "commande 'systemctl' indisponible",
    "doctor_svc_fix":         "sudo systemctl start mc_manager  # ou réinstallez via install.sh",
    "doctor_label_port":      "Port libre",
    "doctor_port_busy":       "occupé par un autre processus",
    "doctor_port_free":       "libre",
    "doctor_port_busy_fix":   "Un autre programme utilise ce port. Changez de port avec 'mc configure', ou fermez l'autre programme.",
    "doctor_all_ok":          "Tout est en ordre.",
    "doctor_has_issues":      "Des points nécessitent votre attention (voir -> ci-dessus).",

    # ── input validation ──────────────────────────────────────────────────────
    "invalid_hour":           "Heure invalide ({val}) : doit être entre 0 et 23.",
    "invalid_minute":         "Minute invalide ({val}) : doit être entre 0 et 59.",
    "invalid_port":           "Port invalide ({val}) : doit être entre 1 et 65535.",
    "invalid_ram":            "Format RAM invalide '{val}'. Exemples valides : 4G, 8G, 4096M.",
    "invalid_cpu":            "Format d'affinité CPU invalide '{val}'. Exemples : 0-7, 0,1,2, 8-15.",
    "invalid_bool":           "Valeur invalide ({val}) : entrez 0 ou 1.",
    "name_empty":             "Le nom du serveur ne peut pas être vide.",
    "rcon_same_as_game_port": "Le port RCON ({rcon}) est identique au port de jeu ({game}). Choisissez un port différent.",
    "schedule_same_time":     "Ouverture et fermeture à la même heure — le serveur ne serait jamais ouvert.",
    "rcon_auth_failed":       "authentification refusée (mauvais mot de passe ?)",
    "rcon_conn_refused":      "connexion refusée (RCON désactivé ? activez enable-rcon=true dans server.properties)",
    "rcon_error_generic":     "erreur : {e}",
    "no_servers_available":   "(aucun)",
    "stopping_server":        "Arrêt de '{name}'...",
    "prompt_retention":       "Rétention des backups en jours (0 = illimité)",
    "invalid_retention":      "Valeur invalide ({val}) : entrez 0 (illimité) ou un nombre de jours positif.",
    "backup_type_manual":     "manuelle",
    "forge_sh_note":          "Note : RAM/flags Java gérés par user_jvm_args.txt pour Forge/NeoForge.",

    # ── mc_cli — argparse ─────────────────────────────────────────────────────
    "cli_commands_title":     "Commandes",
    "cli_target_help":        "Nom ou numéro du serveur (défaut : serveur actif)",
    "help_help":              "Liste complète des commandes",
    "help_version":           "Afficher la version de MC Manager",
    "help_language":          "Changer la langue (fr/en)",
    "help_update":            "Mettre à jour MC Manager vers la dernière version",
    "update_available":       "Mise à jour disponible : {ver} — lancez 'mc update'",
    "update_current":         "MC Manager est déjà à jour (v{ver}).",
    "update_downloading":     "Téléchargement de la version {ver}...",
    "update_done":            "Mis à jour vers la v{ver}. Rouvrez vos terminaux 'mc'.",
    "update_failed":          "Échec de la mise à jour : {e}",
    "update_no_asset":        "Aucun paquet de mise à jour trouvé pour cette plateforme.",
    "update_check_failed":    "Impossible de vérifier les mises à jour (hors ligne ?).",
    "update_daemon_manual":   "Redémarrez le service (root) pour l'appliquer côté daemon : mc daemon restart.",
    "help_intro":             "Gestion de serveurs Minecraft. [{tgt}] = nom ou numéro (défaut : serveur actif).",
    "help_cat_lifecycle":     "Serveur — cycle de vie",
    "help_cat_multi":         "Multi-serveurs",
    "help_cat_config":        "Installation & configuration",
    "help_cat_diag":          "Diagnostic & maintenance",
    "help_cat_general":       "Général",
    "help_footer":            "Astuce : 'mc' seul affiche le tableau de bord de tous les serveurs.",
    "arg_target":             "cible",
    "arg_path":               "chemin",
    "arg_value":              "valeur",
    "language_current":       "Langue actuelle : {lang}",
    "language_usage":         "Changez-la avec : mc language fr  |  mc language en",
    "language_set":           "Langue définie sur : {lang}",
    "language_choose":        "Choisissez votre langue / Choose your language :",
    "help_deploy":            "Déployer un serveur (Vanilla/Paper/Fabric/Forge/NeoForge)",
    "help_add":               "Enregistrer un serveur existant (sans téléchargement)",
    "help_add_path":          "Dossier du serveur existant (demandé si omis)",
    "help_status":            "Tableau de bord",
    "help_use":               "Changer le serveur actif",
    "help_use_target":        "Nom ou numéro du serveur",
    "help_remove":            "Retirer un serveur du registre (fichiers conservés)",
    "help_remove_target":     "Nom ou numéro du serveur",
    "help_doctor":            "Diagnostic complet (Java, RCON, pare-feu, service, port) ; tous les serveurs si cible omise",
    "help_configure":         "Reconfigurer un serveur déjà enregistré",
    "help_start":             "Démarrer le serveur",
    "help_stop":              "Arrêter le serveur proprement",
    "help_stop_force":        "Tuer le processus directement (si RCON ne répond pas)",
    "stop_forced":            "Processus tué (SIGKILL).",
    "help_console":           "Console RCON interactive",
    "help_backup":            "Lancer une sauvegarde ZIP manuelle",
    "help_open":              "Ouvrir le dossier du serveur dans le gestionnaire de fichiers",
    "help_resume":            "Sortir du mode maintenance (le daemon relance le serveur si le mode l'exige)",
    "resume_restart_hint":    "Le daemon va redémarrer le serveur automatiquement (sous ~30 s en 24h/24, ou à l'heure d'ouverture). Pas besoin de 'mc start'.",
    "help_logs":              "Afficher les dernières lignes du journal daemon",
    "help_mode":              "Changer de mode (schedule/always-on/maintenance)",
    "help_schedule":          "Définir les horaires (passe en mode schedule)",
    "help_edit":              "Éditer config.json ou webhooks.json",
    "help_daemon":            "Piloter le service daemon",
    "help_announce":          "Envoyer manuellement l'annonce d'ouverture sur Discord",
    "announce_ok":            "Annonce envoyée sur Discord.",
    "announce_failed":        "Impossible d'envoyer l'annonce : {e}",
    "help_fingerprint":       "Afficher la clé (empreinte) AutoModpack du serveur",
    "fingerprint_result":     "Clé AutoModpack : {fp}",
    "fingerprint_missing":    "Aucune clé AutoModpack trouvée (le serveur doit avoir démarré au moins une fois avec AutoModpack installé).",
    "help_image":             "Gérer l'icône du serveur (server-icon.png)",
    "help_image_add":         "Définir l'icône (glisser-déposer une image)",
    "help_image_rm":          "Supprimer l'icône",
    "help_image_path":        "Chemin vers l'image source",
    "image_set_ok":           "Icône définie ({path})",
    "image_removed_ok":       "Icône supprimée.",
    "image_not_found_icon":   "Aucune icône trouvée dans ce dossier.",
    "image_source_not_found": "Fichier source introuvable : {path}",
    "image_pillow_missing":   "Pillow n'est pas installé. Lancez : pip install Pillow (ou : sudo dnf install python3-pillow)",
    "image_error":            "Erreur lors du traitement de l'image : {e}",
    "image_opening_dialog":   "Ouverture du sélecteur de fichier...",
    "image_no_file_selected": "Aucun fichier sélectionné.",
    "image_no_action":        "Sous-commande requise : add ou rm",
    "logs_nothing":           "(rien à afficher)",

    # ── mc_daemon / mc_core (in-game, visible to players) ────────────────────
    "ingame_closing":         "Attention, fermeture imminente dans {mins} minute(s) ! Mettez-vous a l'abri.",
    "ingame_stopping":        "Arrêt du serveur en cours...",
}

_EN = {
    # ── icons ─────────────────────────────────────────────────────────────────
    "icon_info": "INFO",
    "icon_ok":   "OK",
    "icon_warn": "!",
    "icon_err":  "ERROR",

    # ── yn prompts ────────────────────────────────────────────────────────────
    "yn_yes":    "[Y/n]",
    "yn_no":     "[y/N]",
    "word_default": "default",

    # ── mc_setup ──────────────────────────────────────────────────────────────
    "java_required": "Java is required to start a Minecraft server.",
    "java_download": "Download Java 21 from: https://adoptium.net/ (or: sudo dnf install java-21-openjdk-headless)",
    "java_missing":  "Missing dependency: java",

    # ── mc_servers ────────────────────────────────────────────────────────────
    "no_server_configured": "No server configured. Run \033[96mmc deploy\033[0m to create one.",
    "no_active_server":     "No active server. Select one with \033[96mmc use <name/number>\033[0m (available: {avail}).",
    "server_not_found":     "Server '{target}' not found. Available: {avail}",
    "server_dir_gone":      "Server folder for '{name}' no longer exists: {path}",
    "check_path_or_use":    "Check the path or select another server with: mc use <name/number>",
    "legacy_migrated":      "Existing config migrated to server '{name}' ({path}).",

    # ── mc_core ───────────────────────────────────────────────────────────────
    "already_online":       "Already online.",
    "invalid_dir":          "Invalid folder: {path}",
    "java_not_found_start": "Java not found or inaccessible. Install Java 21+: https://adoptium.net/",
    "server_launched":      "Started on {ip} (PID: {pid})",
    "start_console_hint":   "The server is running in the background. Type 'mc console' to open its console.",
    "start_crashed":        "The server exited immediately after launch (port in use? corrupted JAR?). Check: {log}",
    "start_port_busy":      "Port {port} is already in use: a server is most likely still running. Start cancelled to avoid a duplicate (locked world). Use 'mc stop --force' if the process is stuck.",
    "already_offline":      "Already offline.",
    "stop_sent":            "Stop command sent.",
    "stop_rcon_unreachable": "RCON unreachable: could not send the stop command. The server is still running — use \"mc stop --force\" to kill it.",
    "launch_error":         "Launch error: {e}",
    "maintenance_active":   "Maintenance mode active.",
    "no_webhook":           "No webhook configured.",
    "webhook_error":        "Webhook error: {e}",
    "no_world_found":       "No world folder found.",
    "invalid_paths":        "Invalid paths.",
    "backup_ok":            "{btype} backup OK.",
    "backup_error":         "Backup error: {e}",

    # ── mc_cli — RCON console ─────────────────────────────────────────────────
    "console_offline":      "Server is offline.",
    "console_connected":    "[CONSOLE] Connected. Type 'exit' or Ctrl+C to quit.",
    "console_hint":         "[INFO] Commands are sent via RCON.",
    "console_log_only":     "[INFO] Read-only mode — RCON unavailable, commands disabled.",
    "console_rcon_error":   "RCON unavailable: {msg}",
    "console_disconnect":   "Disconnected.",
    "console_error":        "Console error: {e}",

    # ── mc_cli — dashboard ────────────────────────────────────────────────────
    "no_server_dashboard":  "No server on this machine. Run 'mc deploy' to create one (or 'mc help' for all commands).",
    "active_marker":        "ACTIVE",
    "dir_missing":          "FOLDER NOT FOUND",
    "status_online":        "ONLINE (PID {pid})",
    "status_online_nopid":  "ONLINE",
    "status_offline":       "OFFLINE",
    "mode_schedule":        "Scheduled",
    "mode_always_on":       "24/7",
    "mode_maintenance":     "Maintenance",
    "mode_sched_hours":     "Scheduled ({oh:02d}:{om:02d} - {ch:02d}:{cm:02d})",
    "mode_maint_was":       "Maintenance (was: {was})",
    "field_status":         "Status",
    "field_mode":           "Mode",
    "field_version":        "Version",
    "field_dir":            "Folder",
    "field_port":           "Port",
    "cheatsheet": (
        "\033[96mMain commands:\033[0m\n"
        "  mc deploy              Deploy a new server\n"
        "  mc use <name/number>   Change active server\n"
        "  mc start / mc stop     Start / stop the active server\n"
        "  mc mode <value>        schedule | always-on | maintenance\n"
        "  mc resume              Exit maintenance mode\n"
        "  mc console             RCON console for active server\n"
        "  mc help                Full command list"
    ),
    "no_log_file":          "No daemon.log file found.",

    # ── mc_cli — server management ────────────────────────────────────────────
    "target_info":           "Target: {name} ({sid})",
    "set_active_ok":         "Active server: {name} ({sid})",
    "server_not_found_use":  "Server '{target}' not found.",
    "deregister_warning":    "You are about to remove '{name}' (id {sid}) from the registry.",
    "folder_preserved_info": "Folder (kept, untouched): {path}",
    "confirm_deregister":    "Confirm removal?",
    "deregister_cancelled":  "Cancelled.",
    "deregister_ok":         "Server '{name}' removed from registry.",
    "files_preserved":       "Files kept: {path}",
    "new_active":            "New active server: {name}",
    "no_server_left":        "No servers registered. Run 'mc deploy' or 'mc add'.",
    "folder_opened":         "Opened: {path}",
    "maintenance_activated": "Maintenance enabled. Type 'mc resume' to restart.",
    "mode_set":              "Mode: {mode}",
    "maintenance_disabled":  "Maintenance disabled. Current mode: {mode}",
    "schedule_updated":      "Schedule updated, mode set to 'schedule'.",

    # ── mc_cli — daemon ───────────────────────────────────────────────────────
    "daemon_launching":      "Starting daemon in foreground...",
    "daemon_ok":             "Daemon {label}.",
    "daemon_not_installed":  "The mc_manager service is not installed. Re-run install.sh.",
    "daemon_no_perms":       "Cannot {action} the daemon: root rights required (re-run with sudo).",
    "daemon_error_msg":      "Error: cannot {action} the daemon (code {code}). {detail}",
    "daemon_label_started":  "started",
    "daemon_label_stopped":  "stopped",
    "daemon_label_restarted":"restarted",

    # ── mc_config — smart_ask ─────────────────────────────────────────────────
    "hint_current":          "[Current: {val} | RESET for default: {default}]",
    "hint_default":          "[Default: {val}]",
    "enter_valid_number":    "Please enter a valid number.",

    # ── mc_config — section headers ───────────────────────────────────────────
    "setup_header":          "MC Manager Linux — Configuration",
    "section_base":          "1. Basic Configuration",
    "section_schedule":      "2. Schedule & Backups",
    "section_performance":   "Performance Settings (Advanced)",
    "section_integrations":  "3. Integrations (Optional)",
    "section_prereq":        "MCManager prerequisites check",
    "section_firewall":      "Firewall (firewalld)",

    # ── mc_config — prompts ───────────────────────────────────────────────────
    "prompt_server_name":    "Server name",
    "prompt_motd":           "MOTD description",
    "prompt_dir":            "Server folder",
    "prompt_backup_dir":     "Backup folder",
    "prompt_port":           "Server port",
    "prompt_always_on":      "24/7 server (1=Yes, 0=No)",
    "prompt_open_hour":      "Open hour",
    "prompt_open_min":       "Open minute",
    "prompt_close_hour":     "Close hour",
    "prompt_close_min":      "Close minute",
    "prompt_cpu":            "CPU affinity (e.g. 8-15)",
    "prompt_ram":            "RAM allocation (e.g. 4G, 8G, 4096M)",
    "prompt_jar":            "Executable JAR file",
    "prompt_domain":         "Server domain / link (optional)",
    "prompt_webhook_url":    "Discord webhook URL",
    "prompt_automodpack":    "Enable AutoModpack (0=No, 1=Yes)",

    # ── mc_config — status messages ───────────────────────────────────────────
    "cpu_info":              "-> CPU info: {count} cores detected.",
    "cpu_format_hint":       "-> Affinity format: '8-15' (range), '0,1,2' (list), '0-7' (first 8)",
    "rcon_already_ok":       "RCON already configured.",
    "rcon_not_configured":   "RCON is not configured on this server (required for MC Manager: clean stop, console, backups, warnings).",
    "firewall_ok":           "Port {port} (TCP) opened in firewalld.",
    "firewall_failed":       "Port not opened automatically (firewalld inactive, or root rights required?).",
    "firewall_manual_hint":  "To allow this server manually, run:",
    "automod_fp_detected":   "AutoModpack key detected automatically: {fp}",
    "automod_fp_pending":    "AutoModpack key not yet available (will be detected automatically on next 'mc start').",
    "setup_success":         "Config file updated.",
    "webhooks_edit_hint":    "Edit 'webhooks.json' (in the server folder) to customize Discord messages.",

    # ── mc_config — mc command / systemd install ─────────────────────────────
    "install_mc_header":      "Installing global 'mc' command",
    "install_mc_ok":          "'mc' command installed in /usr/local/bin!",
    "install_mc_new_term":    "Open a new terminal to use 'mc'.",
    "install_mc_perms":       "Root rights required to write to /usr/local/bin.",
    "install_mc_manual":      "Copy manually: {src} -> {dst}",
    "daemon_inst_header":     "Installing Daemon (systemd service)",
    "daemon_inst_ok":         "Service '{name}' installed and started!",
    "daemon_inst_silent":     "Runs in the background. Starts automatically with the system.",
    "daemon_inst_failed":     "Failed to start the service.",
    "daemon_inst_rerun":      "Re-run with sudo.",

    # ── mc_deploy — shared ────────────────────────────────────────────────────
    "deploy_header":          "Server deployment — MC Manager",
    "add_header":             "Add existing server — MC Manager",
    "prompt_install_dir":     "Server install folder",
    "dir_has_server":         "Folder '{path}' already contains a server!",
    "dir_has_server_cont":    "Continue anyway? (risk of overwrite)",
    "deploy_cancelled":       "Deployment cancelled.",
    "add_cancelled":          "Add cancelled.",
    "server_type_header":     "Server type:",
    "choice":                 "Choice",
    "invalid_choice":         "Invalid choice.",
    "java_not_found_forge":   "Java not found or inaccessible.",
    "java_needed_forge":      "Install Java 21+ before deploying Forge or NeoForge.",
    "java_detected":          "Java detected: {ver}",
    "port_conflict_deploy":   "Port {port} is already used by server '{name}'. Choose another.",
    "summary":                "Summary:",
    "summary_name":           "Name    : {name}",
    "summary_type":           "Type    : {stype}",
    "summary_version":        "Version : {ver}",
    "summary_port":           "Port    : {port}",
    "summary_dir":            "Folder  : {path}",
    "confirm_deploy":         "Confirm deployment?",
    "deploy_failed_dl":       "Deployment failed. Check your connection and the chosen version.",
    "jar_run_bat":            "{stype} installed — start via {script}.",
    "jar_main":               "Main JAR: {jar}",
    "deploy_success":         "Server {stype} {ver} deployed successfully!",
    "deploy_dir_info":        "Server folder: {path}",
    "advanced_prompt":        "Configure advanced options now (schedule, CPU/RAM, domain, Discord)?",
    "advanced_saved":         "Advanced configuration saved.",
    "later_hint":             "You can configure them later with: mc configure",
    "start_hint":             "Start the server: mc start",

    # mc add
    "add_dir_prompt":         "Existing server folder",
    "add_dir_not_exists":     "Folder '{path}' does not exist.",
    "add_not_a_server":       "'{path}' does not look like a Minecraft server (no .jar/eula.txt/server.properties found).",
    "add_continue_anyway":    "Continue anyway?",
    "add_jar_prompt":         "Executable JAR file",
    "add_detected":           "Detected: {loader} {ver}",
    "add_not_detected":       "Loader/version not detected automatically (no impact, editable with: mc edit config).",
    "add_port_conflict":      "Port {port} is already used by server '{name}'. Choose another.",
    "add_registered_ok":      "Server '{name}' registered.",

    # RCON setup
    "rcon_step":              "RCON setup",
    "rcon_pass_prompt":       "RCON password",
    "rcon_port_prompt":       "RCON port",
    "rcon_port_conflict":     "RCON port {port} is already used by server '{name}'. Choose another.",
    "rcon_configured_ok":     "RCON configured on port {port}.",

    # AutoModpack setup
    "config_loaded":          "Existing configuration found and loaded from config.json:",
    "config_field_loaded":    "  {label} : {val}",
    "config_nothing_missing": "All essential fields are already configured.",
    "review_config_prompt":   "Do you want to review the full server configuration (schedule, CPU/RAM, Discord...)?",
    "automod_already":        "AutoModpack already present in the mods folder — nothing to install.",
    "automod_checking":       "Checking AutoModpack availability",
    "automod_no_loader":      "AutoModpack is not available for a {loader} server (requires a mod loader: Fabric, Forge or NeoForge).",
    "automod_unavail":        "AutoModpack is not available for Minecraft {ver} with loader {loader}.",
    "automod_avail":          "AutoModpack {aver} available for {loader} {ver}.",
    "automod_desc":           "AutoModpack automatically syncs mods/resource packs from the server to each connecting player (no manual mod installation needed). Optional: without it, players must install the same mods as the server themselves.",
    "automod_prompt":         "Install AutoModpack?",
    "automod_key_found":      "AutoModpack key detected: {fp}",
    "automod_key_later":      "AutoModpack key: will be detected automatically on first 'mc start'.",
    "automod_installed":      "AutoModpack installed in {path}/",

    # downloads / API
    "downloading":            "Downloading{label} ...",
    "download_failed":        "Download failed: {e}",
    "api_error":              "Cannot reach API: {e}",
    "checksum_verified":      "File integrity verified ({algo}).",
    "checksum_failed":        "Integrity check failed for {file} (corrupted download?) — file removed, please retry.",
    "eula_accepted":          "eula.txt accepted automatically.",
    "server_props_gen":       "server.properties generated (port, motd, rcon, gamemode...).",

    # version picker
    "versions_fetching":      "Fetching Minecraft versions ...",
    "versions_header":        "Available versions (last 15 releases):",
    "version_prompt":         "Number or exact version",

    # server type steps
    "step_vanilla":           "Deploying Vanilla",
    "step_paper":             "Deploying Paper",
    "step_fabric":            "Deploying Fabric",
    "step_forge":             "Deploying Forge",
    "step_neoforge":          "Deploying NeoForge",
    "version_not_found":      "Version {ver} not found.",
    "paper_not_available":    "Paper not available for {ver}.",
    "no_forge_versions":      "No Forge version found for {ver}.",
    "forge_selected":         "Forge version selected: {ver}",
    "forge_installing":       "Installing Forge (this may take a few minutes) ...",
    "forge_failed":           "Forge installer failed.",
    "forge_timeout":          "Timeout during Forge installation.",
    "forge_installer_del":    "Forge installer removed.",
    "forge_ok":               "Forge installed — start via run.sh.",
    "neoforge_not_available": "NeoForge not available for {ver}.",
    "neoforge_installing":    "Installing NeoForge ...",
    "neoforge_failed":        "NeoForge installer failed.",
    "neoforge_timeout":       "Timeout during NeoForge installation.",
    "neoforge_installer_del": "NeoForge installer removed.",
    "neoforge_ok":            "NeoForge installed — start via run.sh.",

    # ── mc_doctor ─────────────────────────────────────────────────────────────
    "no_server_cfg_doctor":   "No server configured. Run mc deploy.",
    "doctor_label_dir":       "Server folder",
    "doctor_dir_fix":         "mc configure {name}  # or check that the path exists",
    "doctor_label_java":      "Java",
    "doctor_java_fix":        "Install Java 21+: https://adoptium.net/ (or: sudo dnf install java-21-openjdk-headless)",
    "doctor_label_rcon_cfg":  "RCON configured",
    "doctor_rcon_cfg_ok":     "RCON password present",
    "doctor_rcon_cfg_miss":   "missing",
    "doctor_rcon_cfg_fix":    "mc configure {name}",
    "doctor_label_rcon_live": "RCON reachable",
    "doctor_rcon_offline":    "server offline, not tested",
    "doctor_rcon_live_fix":   "Check enable-rcon=true in server.properties, or restart the server.",
    "doctor_label_firewall":  "Firewall (game port)",
    "doctor_fw_present":      "port '{rule}' open",
    "doctor_fw_absent":       "closed",
    "doctor_fw_no_firewalld": "firewalld unavailable (not installed or inactive)",
    "doctor_label_service":   "mc_manager service",
    "doctor_svc_running":     "running",
    "doctor_svc_stopped":     "installed but stopped",
    "doctor_svc_not_inst":    "service not installed",
    "doctor_svc_no_sc":       "'systemctl' command unavailable",
    "doctor_svc_fix":         "sudo systemctl start mc_manager  # or reinstall via install.sh",
    "doctor_label_port":      "Port available",
    "doctor_port_busy":       "in use by another process",
    "doctor_port_free":       "available",
    "doctor_port_busy_fix":   "Another program is using this port. Change it with 'mc configure', or close the other program.",
    "doctor_all_ok":          "Everything looks good.",
    "doctor_has_issues":      "Some items need attention (see -> above).",

    # ── input validation ──────────────────────────────────────────────────────
    "invalid_hour":           "Invalid hour ({val}): must be between 0 and 23.",
    "invalid_minute":         "Invalid minute ({val}): must be between 0 and 59.",
    "invalid_port":           "Invalid port ({val}): must be between 1 and 65535.",
    "invalid_ram":            "Invalid RAM format '{val}'. Valid examples: 4G, 8G, 4096M.",
    "invalid_cpu":            "Invalid CPU affinity format '{val}'. Examples: 0-7, 0,1,2, 8-15.",
    "invalid_bool":           "Invalid value ({val}): enter 0 or 1.",
    "name_empty":             "Server name cannot be empty.",
    "rcon_same_as_game_port": "RCON port ({rcon}) is the same as the game port ({game}). Choose a different port.",
    "schedule_same_time":     "Open and close times are identical — the server would never be open.",
    "rcon_auth_failed":       "authentication refused (wrong password?)",
    "rcon_conn_refused":      "connection refused (RCON disabled? set enable-rcon=true in server.properties)",
    "rcon_error_generic":     "error: {e}",
    "no_servers_available":   "(none)",
    "stopping_server":        "Stopping '{name}'...",
    "prompt_retention":       "Backup retention in days (0 = unlimited)",
    "invalid_retention":      "Invalid value ({val}): enter 0 (unlimited) or a positive number of days.",
    "backup_type_manual":     "manual",
    "forge_sh_note":          "Note: RAM/Java flags managed by user_jvm_args.txt for Forge/NeoForge.",

    # ── mc_cli — argparse ─────────────────────────────────────────────────────
    "cli_commands_title":     "Commands",
    "cli_target_help":        "Server name or number (default: active server)",
    "help_help":              "Full command list",
    "help_version":           "Show the MC Manager version",
    "help_language":          "Change the language (fr/en)",
    "help_update":            "Update MC Manager to the latest version",
    "update_available":       "Update available: {ver} — run 'mc update'",
    "update_current":         "MC Manager is already up to date (v{ver}).",
    "update_downloading":     "Downloading version {ver}...",
    "update_done":            "Updated to v{ver}. Reopen your 'mc' terminals.",
    "update_failed":          "Update failed: {e}",
    "update_no_asset":        "No update package found for this platform.",
    "update_check_failed":    "Could not check for updates (offline?).",
    "update_daemon_manual":   "Restart the service (root) to apply it daemon-side: mc daemon restart.",
    "help_intro":             "Minecraft server management. [{tgt}] = name or number (default: active server).",
    "help_cat_lifecycle":     "Server — lifecycle",
    "help_cat_multi":         "Multi-server",
    "help_cat_config":        "Setup & configuration",
    "help_cat_diag":          "Diagnostics & maintenance",
    "help_cat_general":       "General",
    "help_footer":            "Tip: 'mc' alone shows the dashboard of all servers.",
    "arg_target":             "target",
    "arg_path":               "path",
    "arg_value":              "value",
    "language_current":       "Current language: {lang}",
    "language_usage":         "Change it with: mc language fr  |  mc language en",
    "language_set":           "Language set to: {lang}",
    "language_choose":        "Choisissez votre langue / Choose your language:",
    "help_deploy":            "Deploy a server (Vanilla/Paper/Fabric/Forge/NeoForge)",
    "help_add":               "Register an existing server (no download)",
    "help_add_path":          "Existing server folder (prompted if omitted)",
    "help_status":            "Server dashboard",
    "help_use":               "Change active server",
    "help_use_target":        "Server name or number",
    "help_remove":            "Remove a server from the registry (files kept)",
    "help_remove_target":     "Server name or number",
    "help_doctor":            "Full diagnostic (Java, RCON, firewall, service, port); all servers if target omitted",
    "help_configure":         "Reconfigure a registered server",
    "help_start":             "Start the server",
    "help_stop":              "Stop the server gracefully",
    "help_stop_force":        "Kill the process directly (when RCON is unavailable)",
    "stop_forced":            "Process killed (SIGKILL).",
    "help_console":           "Interactive RCON console",
    "help_backup":            "Run a manual ZIP backup",
    "help_open":              "Open server folder in the file manager",
    "help_resume":            "Exit maintenance mode (the daemon restarts the server if the mode requires it)",
    "resume_restart_hint":    "The daemon will restart the server automatically (within ~30s in 24/7 mode, or at the opening time). No need to run 'mc start'.",
    "help_logs":              "Show recent daemon log lines",
    "help_mode":              "Change mode (schedule/always-on/maintenance)",
    "help_schedule":          "Set schedule (switches to schedule mode)",
    "help_edit":              "Edit config.json or webhooks.json",
    "help_daemon":            "Control the daemon service",
    "help_announce":          "Manually send the server opening announcement to Discord",
    "announce_ok":            "Announcement sent to Discord.",
    "announce_failed":        "Failed to send announcement: {e}",
    "help_fingerprint":       "Show the server's AutoModpack key (fingerprint)",
    "fingerprint_result":     "AutoModpack key: {fp}",
    "fingerprint_missing":    "No AutoModpack key found (the server must have started at least once with AutoModpack installed).",
    "help_image":             "Manage the server icon (server-icon.png)",
    "help_image_add":         "Set the server icon (drag and drop an image)",
    "help_image_rm":          "Remove the server icon",
    "help_image_path":        "Path to the source image",
    "image_set_ok":           "Icon set ({path})",
    "image_removed_ok":       "Icon removed.",
    "image_not_found_icon":   "No icon found in this server folder.",
    "image_source_not_found": "Source file not found: {path}",
    "image_pillow_missing":   "Pillow is not installed. Run: pip install Pillow (or: sudo dnf install python3-pillow)",
    "image_error":            "Error while processing image: {e}",
    "image_opening_dialog":   "Opening file picker...",
    "image_no_file_selected": "No file selected.",
    "image_no_action":        "Subcommand required: add or rm",
    "logs_nothing":           "(nothing to display)",

    # ── mc_daemon / mc_core (in-game, visible to players) ────────────────────
    "ingame_closing":         "Warning: server closing in {mins} minute(s)! Find shelter.",
    "ingame_stopping":        "Server shutting down...",
}

# T is mutated in place (never reassigned) so that `from mc_lang import T` in
# other modules keeps pointing at the live dictionary after a language switch.
T = {}
_LANG = "fr"


def _apply_language(lang):
    global _LANG
    _LANG = lang if lang in ("fr", "en") else "fr"
    T.clear()
    T.update(_FR if _LANG == "fr" else _EN)


def set_language(lang):
    """Persist the chosen language and apply it to the current process."""
    lang = "en" if str(lang).strip().lower() == "en" else "fr"
    try:
        with open(_LANG_FILE, "w", encoding="utf-8") as f:
            f.write(lang)
    except Exception:
        pass
    _apply_language(lang)
    return lang


_apply_language(_read_saved_language() or "fr")
