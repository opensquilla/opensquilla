<!-- Traduit depuis README.md @ 8794ffbe. Le README anglais fait foi. -->
<!-- Vérifier l'obsolescence : git log 8794ffbe..HEAD -- README.md -->

# OpenSquilla — Agent IA économe en Token

<p align="center">
  <img src="assets/opensquilla-long-logo.png" alt="OpenSquilla logo" width="500">
</p>

<p align="center">
  <b>À budget égal, faites en sorte que votre Agent fasse plus, et le fasse mieux.</b><br>
  Un Agent IA à micro-noyau — routage intelligent, mémoire persistante, bac à sable sécurisé, recherche intégrée et embeddings locaux.
</p>

<p align="center">
  <a href="https://github.com/opensquilla/opensquilla/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/opensquilla/opensquilla/ci.yml?style=for-the-badge" alt="CI"></a>
  <a href="https://opensquilla.ai/"><img src="https://img.shields.io/badge/website-opensquilla.ai-blue?style=for-the-badge" alt="Website"></a>
  <a href="https://github.com/opensquilla/opensquilla/releases"><img src="https://img.shields.io/github/v/release/opensquilla/opensquilla?include_prereleases&style=for-the-badge" alt="GitHub release"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12%2B-blue?style=for-the-badge" alt="Python 3.12+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue?style=for-the-badge" alt="Apache 2.0 License"></a>
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-Hans.md">中文</a> · <a href="README.ja.md">日本語</a> · <b>Français</b> · <a href="README.de.md">Deutsch</a> · <a href="README.es.md">Español</a>
</p>

> Ce document est traduit du [`README.md`](README.md) anglais ; en cas de divergence, la version anglaise fait foi.

---

## Présentation

OpenSquilla est un Agent IA à micro-noyau, économe en Token. Un routeur de modèles
local envoie chaque tour au modèle le moins coûteux capable de le traiter, tandis
que la mémoire persistante, un bac à sable en couches, la recherche web intégrée et
les embeddings exécutés sur l'appareil viennent compléter une boucle de tour unique
et partagée.

Chaque point d'entrée — Web UI, CLI et canaux de chat — passe par cette même boucle,
si bien que la répartition des outils, les nouvelles tentatives et la journalisation
des décisions se comportent de façon identique partout. Une couche de fournisseurs
enfichable dialogue avec OpenRouter, OpenAI, Anthropic, Ollama, DeepSeek, Gemini,
Qwen/DashScope et plus de 20 autres fournisseurs de LLM, sans aucun changement dans
votre code ni dans votre schéma de configuration.

OpenSquilla 0.4.1 est la version actuelle.

Pour une documentation produit orientée tâches, commencez par le
[Guide produit OpenSquilla](README.product.md) ou par l'[index de la
documentation](docs/README.md).

---

## Installation

OpenSquilla fonctionne sous Windows, macOS et Linux. Choisissez la voie qui
correspond à votre cas d'usage.

Les installateurs de bureau, la version portable Windows et l'installation rapide en
terminal vous fournissent une **version** préconstruite — aucun Git requis. Les deux
autres — Installation depuis les sources et Développement depuis les sources —
construisent **à partir d'un dépôt Git** (`git clone` + Git LFS).

Les commandes d'installation de la version publiée utilisent les ressources de release
GitHub publiées. Le zip portable Windows dispose aussi d'un alias
`/releases/latest/download/` pointant vers la version actuelle. Les installations de
wheel Python utilisent des noms de fichier de wheel versionnés, car les installateurs
valident la version intégrée au nom de fichier du wheel.

Pour un usage bureau en 0.4.1, préférez les installateurs de bureau empaquetés issus de la
Release GitHub : `OpenSquilla-0.4.1-mac-arm64.dmg` sous macOS et
`OpenSquilla-0.4.1-win-x64.exe` sous Windows. Le zip portable Windows reste disponible
en tant que paquet de compatibilité héritée pour les scripts et les workflows en
dossier portable.

| Voie | Public | Quand l'utiliser |
| --- | --- | --- |
| [Installateurs de bureau](#desktop-installers) **(recommandé pour le bureau)** | Utilisateurs macOS et Windows | Application de bureau empaquetée |
| [Version portable Windows](#windows-portable-no-python) | Utilisateurs Windows | Compatibilité héritée ; pas de chaîne d'outils Python ; lancement en un seul zip |
| [Installation rapide en terminal](#quick-terminal-install) **(recommandé)** | Utilisateurs finaux sur tout OS | Wheel de la version publiée depuis un terminal |
| [Installation depuis les sources](#install-from-source) | Utilisateurs suivant `main` | Exécuter depuis un dépôt, sans le modifier |
| [Développement depuis les sources](#develop-from-source) | Contributeurs | Modifier, tester ou déboguer les sources |

### Prérequis

| Exigence | Version portable Windows | Installation rapide en terminal | Installation depuis les sources | Développement depuis les sources |
| --- | :---: | :---: | :---: | :---: |
| Python 3.12+ | inclus | via `uv` | via `uv` ou le système | via `uv` |
| Git + Git LFS | — | — | requis | requis |
| `uv` | — | installé s'il manque | recommandé | requis |

Le profil `recommended` par défaut installe **SquillaRouter** — le routeur de modèles
exécuté sur l'appareil d'OpenSquilla — ainsi que ses ressources de modèle ;
`OPENSQUILLA_INSTALL_PROFILE=core` omet ces dépendances. L'indicateur d'onboarding
distinct `--router disabled` conserve les dépendances installées mais désactive le
routeur à l'exécution.

Sous Windows, l'environnement d'exécution ONNX intégré à SquillaRouter a aussi besoin
de l'environnement d'exécution Visual C++. Le lanceur portable Windows et
l'installateur PowerShell depuis les sources l'installent automatiquement via
`winget` ; la voie **Installation rapide en terminal** (`uv tool install`) ne le fait
pas — si le démarrage journalise une erreur `DLL load failed`, installez-le
manuellement (voir [Dépannage](#troubleshooting)). OpenSquilla continue de fonctionner
avec un routage direct vers un modèle unique jusqu'à ce qu'il soit installé.

Lors des installations en terminal sous macOS, l'environnement d'exécution LightGBM de
SquillaRouter peut aussi avoir besoin de la bibliothèque OpenMP du système.
L'application de bureau embarque l'environnement d'exécution dont elle a besoin,
mais l'**Installation rapide en terminal** n'installe pas les bibliothèques
Homebrew/système. Si le démarrage journalise `Library not loaded:
@rpath/libomp.dylib`, exécutez `brew install libomp`, puis redémarrez la passerelle.
OpenSquilla continue de fonctionner avec un routage direct vers un modèle unique
jusqu'à ce qu'il soit installé.

Liens d'installation : [Git](https://git-scm.com/downloads) ·
[Git LFS](https://git-lfs.com/) ·
[uv](https://docs.astral.sh/uv/getting-started/installation/).

<a id="desktop-installers"></a>

### Installateurs de bureau

Les installateurs de bureau 0.4.1 empaquettent la console de contrôle Vue et
l'environnement d'exécution de la passerelle dans une enveloppe Electron.

- macOS Apple Silicon : <https://github.com/opensquilla/opensquilla/releases/download/v0.4.1/OpenSquilla-0.4.1-mac-arm64.dmg>
- Windows x64 : <https://github.com/opensquilla/opensquilla/releases/download/v0.4.1/OpenSquilla-0.4.1-win-x64.exe>

Quittez toute application de bureau OpenSquilla en cours d'exécution avant la mise à
niveau. Les fichiers `~/.opensquilla/config.toml` et les données de session existants
sont réutilisés.

<a id="windows-portable-no-python"></a>

### Version portable Windows (sans Python)

La voie de compatibilité héritée sous Windows — le zip embarque un environnement
d'exécution CPython, si bien qu'aucune installation Python distincte n'est requise.

1. Téléchargez le zip portable actuel :
   <https://github.com/opensquilla/opensquilla/releases/latest/download/OpenSquilla-windows-x64-portable.zip>
2. Extrayez-le dans un dossier accessible en écriture tel que Téléchargements ou
   Documents, puis faites un clic droit sur `Start OpenSquilla.cmd` et choisissez
   **Exécuter en tant qu'administrateur**.
3. Terminez la configuration de premier démarrage, puis ouvrez
   <http://127.0.0.1:18791/control/>.

> [!NOTE]
> Les builds Windows ne sont actuellement pas signés ; le lancement en administrateur est la
> voie prise en charge. Si SmartScreen apparaît, choisissez **Informations
> complémentaires** → **Exécuter quand même**. Si Smart App Control ou une stratégie
> d'entreprise bloque l'application non signée, utilisez plutôt l'[Installation rapide
> en terminal](#quick-terminal-install).

<details>
<summary>Usage avancé de la version portable</summary>

Fournissez une clé OpenRouter avant le premier démarrage :

```powershell
$env:OPENROUTER_API_KEY="sk-..."
Set-ExecutionPolicy -Scope Process Bypass
.\start.ps1
```

Si `OPENROUTER_API_KEY` est défini et qu'aucune configuration locale n'existe, le
lanceur écrit une configuration référençant la variable d'environnement et démarre la
passerelle sans rien demander. S'il n'est pas défini, l'assistant d'onboarding vous
laisse choisir n'importe quel fournisseur pris en charge.

Le zip portable n'installe pas de commande globale `opensquilla`. Pour disposer d'un
terminal où `opensquilla …` fonctionne, exécutez `OpenSquilla Shell.cmd`, ou appelez
directement le lanceur intégré :

```powershell
.\opensquilla.cmd onboard --provider openrouter --api-key-env OPENROUTER_API_KEY
```

</details>

<a id="quick-terminal-install"></a>

### Installation rapide en terminal

La voie recommandée sous Windows, macOS et Linux. `uv` installe OpenSquilla dans son
propre environnement isolé et gère son propre Python — aucun Python système requis.
Cette voie n'installe que des versions publiées ; pour `main`, des branches de
développement ou des dépôts locaux, utilisez l'[Installation depuis les
sources](#install-from-source).

**1. Installer `uv`** — à ignorer si `uv --version` fonctionne déjà.

Linux / macOS :

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
. "$HOME/.local/bin/env"
```

Windows PowerShell :

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
$env:Path = "$env:USERPROFILE\.local\bin;" + $env:Path
```

**2. Installer OpenSquilla** — la même commande sur toutes les plateformes.

```sh
uv tool install --python 3.12 "opensquilla[recommended] @ https://github.com/opensquilla/opensquilla/releases/download/v0.4.1/opensquilla-0.4.1-py3-none-any.whl"
```

Cela installe le wheel OpenSquilla depuis l'URL de release, puis laisse `uv`
télécharger les dépendances déclarées par les extras sélectionnés. L'extra
`recommended` par défaut inclut les dépendances d'exécution de SquillaRouter telles
que ONNX Runtime, LightGBM, NumPy et tokenizers ; une première installation nécessite
donc un accès réseau, à moins que ces wheels ne soient déjà en cache. `uv` n'installe
pas les environnements d'exécution natifs du système, comme `libomp` sous macOS ou le
Visual C++ Redistributable sous Windows ; consultez le [Dépannage](#troubleshooting)
si l'environnement d'exécution du routeur signale une erreur de chargement de
bibliothèque native.

**3. Configurer et exécuter.**

```sh
opensquilla onboard
opensquilla gateway run
```

> [!NOTE]
> Si `opensquilla` est introuvable juste après une installation `uv` neuve, ouvrez un
> nouveau terminal, ou réexécutez la ligne PATH de l'étape 1.

Pour une installation entièrement épinglée, utilisez l'URL de wheel versionnée :
`https://github.com/opensquilla/opensquilla/releases/download/v0.4.1/opensquilla-0.4.1-py3-none-any.whl`.

<a id="install-from-source"></a>

### Installation depuis les sources

Utilisez cette voie pour exécuter OpenSquilla depuis un dépôt sans le modifier. Le
clone ne sert que de source du paquet pour l'installateur ; après l'installation,
utilisez la commande `opensquilla` — n'exécutez pas `uv run`. Choisissez plutôt
[Développement depuis les sources](#develop-from-source) si vous comptez modifier le
code.

1. **Cloner avec les ressources LFS**

   ```sh
   git lfs install
   git clone https://github.com/opensquilla/opensquilla.git
   cd opensquilla
   git lfs pull --include="src/opensquilla/squilla_router/models/**"
   ```

2. **Exécuter l'installateur**

   **macOS / Linux**

   ```sh
   bash scripts/install_source.sh
   ```

   **Windows PowerShell**

   ```powershell
   powershell -ExecutionPolicy Bypass -File ./scripts/install_source.ps1
   ```

   Le script installe `.[recommended]` (SquillaRouter + mémoire + modèles locaux)
   dans un environnement utilisateur dédié via `uv tool install`, en se rabattant sur
   `python -m pip install --user` lorsque `uv` n'est pas disponible. Ouvrez un nouveau
   terminal si `opensquilla` n'est pas dans le `PATH` après l'installation.

3. **(facultatif) Installer des extras avancés.** La plupart des canaux — Feishu,
   Telegram, DingTalk, QQ, WeCom, Slack et Discord — fonctionnent depuis
   l'installation de base. Les extras optionnels sont :

   - `matrix` — canal Matrix (installe aussi `matrix-nio`)
   - `matrix-e2e` — canal Matrix avec chiffrement de bout en bout (nécessite libolm)
   - `document-extras` — génération de PDF via WeasyPrint

   ```sh
   OPENSQUILLA_INSTALL_EXTRAS=matrix bash scripts/install_source.sh        # macOS / Linux
   ```

   ```powershell
   powershell -ExecutionPolicy Bypass -File ./scripts/install_source.ps1 -Extras matrix   # Windows
   ```

4. **Configurer et exécuter** — voir [Configuration](#configuration).

<details>
<summary>Installation depuis les sources — prérequis terminal et options de l'installateur</summary>

**Installer les prérequis (Git, Git LFS, uv) depuis un terminal**

Windows PowerShell :

```powershell
winget install --id Git.Git -e
winget install --id GitHub.GitLFS -e
powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
git lfs install
```

macOS (Homebrew) :

```sh
brew install git git-lfs uv
git lfs install
```

Debian / Ubuntu :

```sh
sudo apt update && sudo apt install -y git git-lfs
curl -LsSf https://astral.sh/uv/install.sh | sh
git lfs install
```

Sous Fedora, utilisez `sudo dnf install -y git git-lfs` ; sous Arch, utilisez
`sudo pacman -S --needed git git-lfs` ; puis installez `uv` avec la commande `curl`
ci-dessus. Les modifications du PATH effectuées par ces installateurs s'appliquent aux
nouvelles sessions de terminal.

**Variables d'environnement de l'installateur et vérifications du PATH**

```sh
OPENSQUILLA_INSTALL_PROFILE=core   bash scripts/install_source.sh   # runtime minimal, sans SquillaRouter
OPENSQUILLA_INSTALL_DRY_RUN=1      bash scripts/install_source.sh   # afficher uniquement le plan
```

Vérifiez quel `opensquilla` votre shell exécute avec `command -v opensquilla`
(macOS/Linux) ou `where.exe opensquilla` (Windows). S'il n'est pas dans le `PATH`,
exécutez `uv tool update-shell`. Après une réinstallation depuis un dépôt local,
redémarrez la passerelle afin qu'elle charge le paquet mis à jour.

</details>

<a id="develop-from-source"></a>

### Développement depuis les sources

Utilisez cette voie lorsque vous travaillez sur le code source d'OpenSquilla :
apporter des changements, exécuter des tests ou déboguer le comportement par rapport à
ce dépôt. Ce n'est pas la voie d'installation normale. Contrairement à
[Installation depuis les sources](#install-from-source), cette voie nécessite `uv` :
`uv sync` crée un `.venv` local au dépôt, et `uv run` exécute les commandes par rapport
aux fichiers de ce dépôt.

```sh
uv sync --extra recommended --extra dev
uv run opensquilla --help
```

L'extra `recommended` inclut aussi SquillaRouter pour le développement ; l'extra `dev`
installe les outils de test, de lint et de vérification de types. Installez des extras
supplémentaires dans le même environnement que celui que vous exécutez :

```sh
uv sync --extra recommended --extra dev --extra matrix
uv run opensquilla channels status matrix --json
```

Dans ce mode, préfixez chaque commande `opensquilla` de la
[Configuration](#configuration) par `uv run`. Ne déboguez pas un dépôt de développement
via une commande `opensquilla` locale à l'utilisateur — cette commande s'exécute dans
un environnement Python différent.

### Désinstallation

Supprimez OpenSquilla avec `opensquilla uninstall`. Il conserve vos données par défaut
et ne supprime que le programme :

```sh
opensquilla uninstall --dry-run   # prévisualiser ce qui serait supprimé et conservé
opensquilla uninstall             # supprimer le programme, conserver vos données
```

Pour supprimer aussi les données, activez-le explicitement :

```sh
opensquilla uninstall --purge-state    # sessions, journaux, cache, planificateur, mémoire
opensquilla uninstall --purge-config   # config.toml et secrets (.env)
opensquilla uninstall --purge-all      # tout (vous demande de saisir une confirmation)
```

La passerelle en cours d'exécution est d'abord drainée et arrêtée, la suppression
reste à l'intérieur du répertoire personnel d'OpenSquilla, et les installations
Docker/bureau reçoivent à la place des étapes de suppression guidées. Consultez
[`docs/cli.md`](docs/cli.md#uninstall) pour la référence complète.

---

## Confidentialité de l'installation

OpenSquilla utilise une télémétrie d'installation anonyme pour estimer le nombre
d'installations, l'adoption des versions et la compatibilité d'exécution. Les données
sont envoyées au premier démarrage de la passerelle et une fois par version
d'OpenSquilla. Les envois utilisent un délai d'expiration court et ne bloquent jamais
le démarrage.

Ce qui est envoyé :

- la version du schéma
- un condensé `install_id` stable généré localement
- la version d'OpenSquilla
- le type d'événement (`install` ou `version_seen`)
- la méthode d'installation (`pip`, `source`, `docker`, `desktop` ou `unknown`)
- le système d'exploitation, la version de l'OS, l'architecture du processeur et la
  version majeure/mineure de Python
- les horodatages de première observation et d'envoi
- un marqueur d'environnement CI/test (`ci_environment`)

L'`install_id` est un condensé local SHA-256 à sens unique dérivé des adresses MAC
utilisables, puis des adresses IP locales lorsqu'aucune MAC n'est disponible, avec une
valeur de repli aléatoire persistante. Les valeurs MAC/IP brutes ne sont pas envoyées.

Ce qui n'est pas envoyé : noms d'utilisateur, noms d'hôte, chemins, clés d'API,
configuration des fournisseurs, contenu de chat/session/mémoire/Agent, noms de fichiers
ou contenu de fichiers. L'IP source peut être visible des serveurs HTTP au niveau de la
couche de transport, mais ne fait pas partie de la charge utile.

Pour la désactiver :

```sh
OPENSQUILLA_TELEMETRY_DISABLED=true
```

Les déploiements avancés peuvent utiliser leur propre point de terminaison :

```sh
OPENSQUILLA_TELEMETRY_ENDPOINT=https://example.com/v1/install
```

---

<a id="configuration"></a>

## Configuration

### Configuration de premier démarrage

`opensquilla onboard` est l'assistant interactif de premier démarrage. Il écrit le
fichier de configuration actif et conserve les secrets des fournisseurs dans des
variables d'environnement lorsque vous passez `--api-key-env`. Le routeur a pour valeur
par défaut `recommended` (SquillaRouter sur les fournisseurs pris en charge) ; passez
`--router disabled` pour un routage direct vers un modèle unique.

```sh
opensquilla onboard                # assistant interactif complet
opensquilla onboard --if-needed    # idempotent : sûr pour les scripts et réinstallations
opensquilla onboard --minimal      # fournisseur uniquement ; ignore les canaux et la recherche
opensquilla onboard status         # inspecter chaque section de configuration sans écrire
```

En SSH, en CI ou dans tout environnement sans TTY, utilisez la forme non interactive —
conservez le secret dans l'environnement et passez son **nom**, pas sa valeur :

**Linux / macOS**

```sh
export OPENROUTER_API_KEY="sk-..."
opensquilla onboard --provider openrouter --api-key-env OPENROUTER_API_KEY
```

**Windows PowerShell**

```powershell
$env:OPENROUTER_API_KEY="sk-..."
opensquilla onboard --provider openrouter --api-key-env OPENROUTER_API_KEY
```

OpenRouter n'est qu'un exemple — substituez n'importe quel fournisseur pris en charge
et sa variable de clé d'API.

Reconfigurez une section plus tard sans refaire l'assistant complet (ces exemples
supposent que la clé d'API concernée est déjà dans l'environnement) :

```sh
opensquilla configure provider --provider openai --model gpt-4o --api-key-env OPENAI_API_KEY
opensquilla configure router --router recommended
opensquilla configure search   --search-provider duckduckgo
opensquilla configure search   --search-provider exa --api-key-env EXA_API_KEY
opensquilla configure channels
```

Sections : `provider`, `router`, `channels`, `search`, `image-generation`,
`memory-embedding`. La Web UI expose le même catalogue et le même modèle de statut sur
`/control/setup` : Provider et Router constituent la voie rapide, tandis que Channels,
Search, Image generation et Memory embedding se trouvent dans le Capability Center et
peuvent être configurés plus tard. Des canaux vides sont traités comme un
désengagement, pas comme une configuration échouée.

**Ordre de chargement de la configuration :** `OPENSQUILLA_GATEWAY_CONFIG_PATH` →
`./opensquilla.toml` → `~/.opensquilla/config.toml` → valeurs par défaut intégrées.
Pour les secrets individuels, les valeurs de l'environnement l'emportent toujours sur
les valeurs des fichiers.

### Migrer depuis OpenClaw ou Hermes Agent

Si vous avez déjà un état sous `~/.openclaw` ou `~/.hermes`, exécutez d'abord un dry run
pour inspecter le rapport de migration, puis appliquez-le explicitement :

```sh
opensquilla migrate openclaw --json
opensquilla migrate openclaw --apply

opensquilla migrate hermes --json
opensquilla migrate hermes --apply
```

Utilisez `opensquilla migrate --source openclaw,hermes --apply` pour importer les deux
répertoires personnels par défaut. N'ajoutez `--migrate-secrets` qu'après avoir examiné
le rapport du dry run. Consultez [`MIGRATION.md`](MIGRATION.md) pour les chemins
personnalisés et la gestion des conflits.

### Exécution

```sh
opensquilla gateway run                # premier plan, 127.0.0.1:18791
opensquilla gateway start --json       # arrière-plan + attente de l'état de santé
opensquilla chat                       # REPL interactif
opensquilla agent -m "your prompt"     # exécution unique, adaptée à l'automatisation
```

Ouvrez la Web UI sur <http://127.0.0.1:18791/control/>. La vue **Health** (santé)
indique si OpenSquilla est prêt, ce qui ne l'est pas, et les prochaines étapes de
rétablissement. Depuis la CLI, exécutez :

```sh
opensquilla doctor
opensquilla doctor --json
opensquilla doctor --config ./opensquilla.toml --json
```

`/health` et `/healthz` sont des points de terminaison de liveness légers pour les
vérifications de processus. `opensquilla doctor` et la vue Health de la Web UI sont les
surfaces de readiness pour la configuration des fournisseurs, la mémoire, les journaux,
la recherche, les canaux, la posture du bac à sable, le routeur, la génération d'images
et les conseils de rétablissement. Appuyez sur `Ctrl+C` pour arrêter une passerelle au
premier plan.

Les autres groupes de commandes incluent `sessions`, `skills`, `memory`, `migrate`,
`cron`, `channels`, `providers`, `models` et `cost`. Exécutez `opensquilla --help` ou
`opensquilla <groupe> --help` pour les détails.

<details>
<summary>Configuration avancée — vérifier un canal, liaison réseau publique, Docker</summary>

**Connecter et vérifier un canal de messagerie**

Enregistrer un canal est un changement de configuration, pas une preuve de
connectivité à l'exécution. Redémarrez la passerelle après des modifications de canal,
puis vérifiez le canal en direct :

```sh
opensquilla gateway restart
opensquilla channels status <name> --json
```

Considérez un canal comme connecté uniquement lorsque la charge utile de statut indique
`enabled=true`, `configured=true` et `connected=true`. Feishu utilise par défaut le
mode websocket, Telegram le polling, et Slack peut utiliser le Socket Mode — aucun de
ces modes ne nécessite d'URL publique. Le mode webhook de Feishu, le mode webhook de
Telegram, le mode webhook de Slack et WeCom nécessitent une URL publique, accessible
par le fournisseur.

**Liaison réseau publique**

Pour atteindre la Web UI depuis une autre machine, liez la passerelle à toutes les
interfaces et utilisez l'IP publique de l'hôte :

```sh
opensquilla gateway run --listen 0.0.0.0 --port 18791
```

L'accès public requiert également que le pare-feu de l'hôte ou le groupe de sécurité
cloud autorise le trafic TCP entrant sur ce port. N'exposez pas la passerelle avec
`[auth] mode = "none"` — configurez l'authentification par token avant de lier à
`0.0.0.0`.

**Docker**

La voie compose exécute une image `opensquilla:local` que vous construisez vous-même.
Construisez-la à partir d'un dépôt source dont les ressources de routeur Git LFS ont été
récupérées (voir [Installation depuis les sources](#install-from-source) pour le clone
et `git lfs pull`) :

```sh
docker build -t opensquilla:local .
```

`./start.sh` (ou `start.ps1` sous Windows) exécute ensuite `docker compose up -d` et
suit les journaux de la passerelle. Docker évite une chaîne d'outils Python sur l'hôte —
pas la construction de l'image locale.

</details>

Les niveaux de fournisseurs, le réglage du bac à sable, la génération d'images et les
paramètres de concurrence se trouvent dans `opensquilla.toml.example`.

---

## Nouveautés de la 0.4.1

OpenSquilla 0.4.1 est une version de maintenance pour la ligne bureau et Control UI :

- **Fiabilité du bureau** - les vérifications de la passerelle empaquetée couvrent
  désormais le mode Coding, `code-task` et le démarrage de SquillaRouter, et la gestion
  des fenêtres/artefacts de bureau est plus stable.
- **Prise en charge client en six langues** - la Control UI et le client de bureau
  prennent en charge l'anglais, le chinois simplifié, le japonais, le français,
  l'allemand et l'espagnol sur les surfaces de premier affichage et de réglages.
- **Mode Coding et empaquetage du routeur** - les builds de bureau échouent rapidement
  si les ressources du routeur sont manquantes ou encore des pointeurs Git LFS, ce qui
  évite des paquets de release dégradés.
- **Télémétrie et finitions Windows** - la télémétrie d'installation ignore les
  environnements CI et de test, et les ressources de bureau Windows utilisent le logo
  OpenSquilla.
- **Gouvernance de la ligne principale** - les pull requests ordinaires et
  l'intégration des releases sont alignées autour de `main`, les branches de
  mainteneur étant réservées aux travaux de release, hotfix, staging, intégration et
  bac à sable.

Notes complètes : [`CHANGELOG.md`](CHANGELOG.md) ·
[`docs/releases/0.4.1.md`](docs/releases/0.4.1.md).

## Nouveautés de la 0.2.1

OpenSquilla 0.2.1 est une version de maintenance axée sur le démarrage des paquets de
release et la fiabilité des Agents à longue durée d'exécution :

- **Démarrage de la version portable Windows** — le lanceur portable détecte et amorce
  mieux l'environnement d'exécution Visual C++ requis par le routeur ONNX intégré.
- **Tours d'Agent à longue durée** — les sessions WebUI à forte intensité d'outils se
  rétablissent plus proprement après des résultats d'outils surdimensionnés, des appels
  d'outils mal formés, des transferts de livraison d'artefacts et des réponses finales
  dégradées.
- **Sortie WebUI plus propre** — les marqueurs d'artefacts générés sont tenus à l'écart
  de la relecture de chat normale tandis que les fichiers livrés restent visibles.
- **Score de rappel de la mémoire** — les vecteurs d'embedding locaux et compatibles
  OpenAI sont normalisés avant la recherche sémantique, et les fortes correspondances
  de mots-clés restent exploitables lorsque les scores vectoriels sont faibles.

Notes complètes : [`CHANGELOG.md`](CHANGELOG.md) ·
[notes de version](https://opensquilla.ai/news/).

## Nouveautés de la 0.2.0

Cette version étend OpenSquilla à la migration, au chat en CLI, aux canaux, à la
planification et aux travaux d'outils de longue durée :

- **Voie de migration depuis des répertoires personnels d'Agent existants** —
  `opensquilla migrate` prévisualise et applique les imports depuis des répertoires
  personnels OpenClaw/Hermes existants, y compris la mémoire, les fichiers de persona,
  les compétences, la configuration MCP/canal, la gestion des conflits et les rapports
  de migration.
- **CLI de chat utilisable** — `opensquilla chat` dispose d'une interface terminal
  stable, d'une sortie en streaming, d'une saisie mise en file d'attente, d'une
  découverte du mode slash, de bandeaux d'outils/de statut, et d'un comportement
  d'invite en direct plus déterministe.
- **Automatisation cron multi-surface** — les tâches cron couvrent désormais les
  planifications structurées, les exécutions exactes/à intervalle/cron tenant compte du
  fuseau horaire, la livraison par canal ou webhook, les destinations en cas d'échec,
  les exécutions manuelles, ainsi que la parité WebUI/CLI/RPC.
- **Meilleurs canaux Feishu et Discord** — les adaptateurs de canal exposent des
  métadonnées de capacité plus claires, une gestion des messages privés/de groupe plus
  sûre, des chemins de fichiers et d'artefacts natifs, et un comportement amélioré des
  pièces jointes/fils, tandis que les actions privilégiées restent à portée limitée.
- **Tours de longue durée plus robustes** — les tours échoués sont tenus à l'écart de la
  relecture du fournisseur, les appels d'outils mal formés sont gérés plus sûrement, et
  les nouvelles tentatives soumises à approbation attendent les décisions de
  l'opérateur.
- **Budget de contexte et d'outils plus intelligent** — la compaction selon le budget du
  fournisseur, la préservation du cache de prompt, des résultats d'outils bornés et une
  concurrence consciente des effets de bord rendent les grandes sessions à forte
  intensité d'outils plus prévisibles.
- **Finitions de la Web UI et des releases** — l'ordonnancement par récence, la mise en
  page des tableaux, les contrôles mobiles, les notifications en double, les formulaires
  de configuration, les URL de release et les voies d'installation sont resserrés pour
  la 0.2.0.

Notes complètes : [`CHANGELOG.md`](CHANGELOG.md) ·
[notes de version](https://opensquilla.ai/news/).

---

## Fonctionnalités clés

| Capacité | Ce qu'elle fait |
| --- | --- |
| **Routage économe en Token** | `SquillaRouter` — un classifieur local LightGBM + ONNX présent dans l'extra `recommended` — évalue chaque tour selon la longueur, la langue, le code, les mots-clés et les embeddings sémantiques, puis l'achemine à travers quatre niveaux (C0–C3 ; les anciens noms T0–T3 sont des alias) vers le modèle le moins coûteux capable de le traiter. La classification s'exécute sur l'appareil ; votre prompt ne quitte jamais la machine pour prendre cette décision. |
| **Raisonnement et prompts adaptatifs** | OpenSquilla ne demande un raisonnement étendu que pour les tours que le routeur évalue comme complexes, et le prompt système s'adapte à la complexité de la tâche — léger pour les tours triviaux, instructions complètes pour les tours complexes. |
| **Plus de 20 fournisseurs de LLM** | Le registre des fournisseurs vise plus de 20 backends de LLM — OpenRouter, OpenAI, Anthropic, Ollama, DeepSeek, Gemini, DashScope/Qwen, Moonshot, Mistral, Groq, Zhipu, SiliconFlow, vLLM, LM Studio, et bien d'autres, avec une sélection principal-plus-repli ; l'onboarding de premier démarrage expose le sous-ensemble vérifié. |
| **Compétences à la demande et MCP** | 15 compétences intégrées (coding, GitHub, cron, pptx/docx/xlsx/pdf, résumé, tmux, météo, et plus encore) ne se chargent que lorsque la tâche en a besoin. OpenSquilla est un client MCP, et peut aussi s'exécuter comme serveur MCP — `opensquilla mcp-server run` nécessite l'extra `mcp` (installez `opensquilla[recommended,mcp]`). Les compétences peuvent être créées, installées et publiées depuis la CLI. |
| **Mémoire locale persistante** | Un `MEMORY.md` soigneusement constitué, complété par des notes Markdown datées, interrogé via la recherche par mots-clés en texte intégral de SQLite et le rappel sémantique de `sqlite-vec`. Les embeddings s'exécutent sur l'appareil via un ONNX intégré, ou basculent vers OpenAI/Ollama. Une décroissance exponentielle facultative et une consolidation « dream » activable sur option sont disponibles. |
| **Bac à sable de sécurité en couches** | Trois niveaux de stratégie (Standard / Strict / Locked) sur une matrice de permissions. Bubblewrap isole l'exécution de code sous Linux ; le backend Seatbelt de macOS ne fait pour l'instant que générer des profils (l'exécution est à venir), et il n'existe pas encore de backend de bac à sable sous Windows. Un registre de refus (denial ledger) met automatiquement en pause les exécutions autonomes après des refus répétés, les sorties rejetées sont purgées, et les métadonnées de compétences ainsi que les résultats d'outils sont échappés en XML contre l'injection de prompt. |
| **Outils intégrés** | Lecture/écriture/édition de fichiers, shell et processus en arrière-plan, git, recherche web (DuckDuckGo, Bocha, Brave, Tavily ou Exa) et récupération derrière une protection SSRF, création de feuilles de calcul/PPTX/PDF, génération d'images et synthèse vocale. |
| **Passerelle unifiée** | Un serveur ASGI Starlette sur `127.0.0.1:18791` avec RPC WebSocket et une console de contrôle intégrée (`/control/`). La Web UI, la CLI et les canaux Terminal, WebSocket, Slack, Telegram, Discord, Feishu, DingTalk, WeCom, Matrix et QQ partagent tous un même `TurnRunner`. |
| **Sessions durables, sous-Agents et planification** | Stockage des sessions, des transcriptions et des relectures adossé à SQLite, avec des espaces de travail par Agent. Les Agents engendrent des sous-Agents à profondeur bornée, et un `SchedulerEngine` doté d'un analyseur cron intégré exécute des tâches récurrentes via `opensquilla cron`. |
| **Contrôles de l'opérateur** | Les approbations avec humain dans la boucle peuvent mettre en pause les appels d'outils sensibles en attendant une décision ; les récapitulatifs de Token et de coût par tour et par session (`opensquilla cost`) ainsi que les diagnostics sont accessibles depuis la CLI et la Web UI. |

Documentation MetaSkill : [`docs/features/meta-skills.md`](docs/features/meta-skills.md),
[`docs/features/meta-skill-user-guide.md`](docs/features/meta-skill-user-guide.md),
et [`docs/authoring/meta-skills.md`](docs/authoring/meta-skills.md).

---

## Résultats des tests de performance

Résultats moyens de PinchBench 1.2.1 sur 25 tâches :

| Agent | Modèle de base | Score moyen | Total des tokens d'entrée | Total des tokens de sortie | Coût total |
| --- | ---: | ---: | ---: | ---: | ---: |
| OpenSquilla | Routeur de modèles (Opus4.7, GLM5.1, DS4 Flash) | 0.9251 | 1,721,328 | 61,475 | $0.688 |
| OpenClaw | Claude Opus 4.7 | 0.9255 | 3,066,243 | 50,890 | $6.233 |

Le score est la moyenne sur les 25 tâches ; les comptes de tokens et le coût sont les
totaux de l'exécution complète.

---

<a id="troubleshooting"></a>

## Dépannage

<details>
<summary>macOS : <code>Library not loaded: @rpath/libomp.dylib</code></summary>

Si le démarrage journalise `Library not loaded: @rpath/libomp.dylib` depuis
`lightgbm/lib/lib_lightgbm.dylib`, OpenSquilla continue de fonctionner avec un routage
direct vers un modèle unique, mais l'environnement d'exécution `SquillaRouter` intégré
reste inactif jusqu'à ce que l'environnement d'exécution OpenMP de macOS soit installé.

L'application de bureau embarque l'environnement d'exécution natif dont elle a
besoin. Si vous avez utilisé l'installation rapide en terminal ou l'installation depuis
les sources via un shell, installez `libomp` avec Homebrew et redémarrez la passerelle :

```sh
brew install libomp
opensquilla gateway restart
```

</details>

<details>
<summary>Windows : <code>DLL load failed</code> / environnement d'exécution Visual C++</summary>

Si le démarrage journalise `DLL load failed while importing
onnxruntime_pybind11_state`, OpenSquilla continue de fonctionner avec un routage direct
vers un modèle unique, mais l'environnement d'exécution `SquillaRouter` intégré reste
inactif jusqu'à ce que le Visual C++ Redistributable pour Visual Studio 2015–2022 (x64)
soit installé.

Le lanceur portable Windows et l'installateur PowerShell depuis les sources tentent
d'installer le redistributable via `winget`. Si vous avez utilisé l'installation rapide
en terminal, ou si `winget` n'est pas disponible, installez-le manuellement et
redémarrez PowerShell : <https://aka.ms/vs/17/release/vc_redist.x64.exe>. Puis rétablissez
le routeur recommandé :

```powershell
opensquilla onboard --provider openrouter --api-key-env OPENROUTER_API_KEY --router recommended
opensquilla gateway restart
```

</details>

---

## Remerciements

OpenSquilla s'inspire d'[OpenClaw](https://github.com/openclaw/openclaw). Le contenu
tiers intégré est attribué dans
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

Les contributeurs de la communauté sont remerciés dans
[`CONTRIBUTORS.md`](CONTRIBUTORS.md), avec notamment des notes d'attribution propres à
chaque release pour les travaux fusionnés par squash ou rejoués.

---

## Contribuer

Les contributions de toute nature sont les bienvenues — rapports de bugs, idées de
fonctionnalités, documentation, nouveaux adaptateurs de fournisseurs ou de canaux,
compétences et travail sur le runtime central. Consultez
[`CONTRIBUTING.md`](CONTRIBUTING.md), puis ouvrez une issue ou une pull request sur
[GitHub](https://github.com/opensquilla/opensquilla).

[Code de conduite](CODE_OF_CONDUCT.md) · [Sécurité](SECURITY.md) ·
[Support](SUPPORT.md) · [Licence](LICENSE) (Apache-2.0)
