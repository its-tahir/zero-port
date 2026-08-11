"""Turn process signals into a description a developer actually recognises.

The rules are ordered by confidence, not by convenience:

1. a description the user set for that port
2. the command line, which is the strongest automatic signal
3. the executable name
4. the port number, but only when the process told us nothing
5. a generic family label

Nothing here guesses. If the evidence is weak the answer is vague on purpose —
"Python process" is a useful truth, "FastAPI Backend" invented from port 8000
is not.
"""

from __future__ import annotations

import re
from typing import Dict, List, Mapping, Optional, Pattern, Tuple

from app.models.port_info import ProcessInfo

UNKNOWN = "Unknown service"


def _token(word: str) -> str:
    """Match ``word`` as a standalone token, not as part of ``vite-app``."""
    return rf"(?<![\w.\-]){word}(?![\w.\-])"


def _path_segment(word: str) -> str:
    """Match ``word`` as a whole directory or file stem inside a path.

    ``\\vite\\bin`` and ``\\vite.js`` match; ``\\vite-app\\`` does not.
    """
    return rf"[\\/]{word}(?:\.[a-z0-9]+)?(?![\w.\-])"


def _compile(patterns: List[Tuple[str, str]]) -> List[Tuple[Pattern[str], str]]:
    return [(re.compile(p, re.IGNORECASE), label) for p, label in patterns]


# ---------------------------------------------------------------------------
# Command-line rules — most specific first.
# ---------------------------------------------------------------------------

CMDLINE_RULES: List[Tuple[Pattern[str], str]] = _compile(
    [
        # Python web / ASGI / WSGI
        (_token("uvicorn"), "FastAPI / Uvicorn"),
        (_token("hypercorn"), "ASGI server (Hypercorn)"),
        (_token("daphne"), "Django Channels (Daphne)"),
        (_token("gunicorn"), "Gunicorn (WSGI)"),
        (_token("waitress-serve") + r"|waitress\.serve", "Waitress (WSGI)"),
        (r"manage\.py|" + _token("django"), "Django"),
        (_token("flask"), "Flask"),
        (_token("streamlit"), "Streamlit"),
        (_token("gradio"), "Gradio"),
        (r"jupyter[\-\s]?(?:lab|notebook|server)?|" + _token("notebook"), "Jupyter"),
        (r"http\.server|SimpleHTTPServer", "Python HTTP server"),
        (_token("celery"), "Celery worker"),
        (r"fastmcp|" + _token("mcp") + r"|mcp[\-_]server", "MCP server"),
        (_token("fastapi"), "FastAPI"),
        (_token("litestar"), "Litestar"),
        (_token("airflow"), "Apache Airflow"),
        (_token("mlflow"), "MLflow"),
        (r"vllm|text-generation-launcher", "LLM inference server"),
        # Node / JavaScript
        (
            _token("next") + r"|" + _path_segment("next") + r"|next[\-\s]server",
            "Next.js",
        ),
        (_token("nuxt") + r"|" + _path_segment("nuxt"), "Nuxt"),
        (_token("vite") + r"|" + _path_segment("vite"), "Vite dev server"),
        (r"react-scripts", "Create React App"),
        (r"webpack-dev-server|webpack\s+serve", "Webpack dev server"),
        (r"@angular|" + _token("ng") + r"\s+serve", "Angular dev server"),
        (_token("astro") + r"|" + _path_segment("astro"), "Astro"),
        (_token("remix") + r"|" + _path_segment("remix"), "Remix"),
        (_token("sveltekit") + r"|svelte-kit", "SvelteKit"),
        (_token("storybook") + r"|" + _path_segment("storybook"), "Storybook"),
        (_token("nodemon"), "Node.js (nodemon)"),
        (_token("nest") + r"|" + _path_segment("nest"), "NestJS"),
        (_token("strapi"), "Strapi"),
        (_token("expo"), "Expo dev server"),
        (_token("serve") + r"\s+-s|http-server", "Static file server"),
        (r"json-server", "JSON Server"),
        (_token("turbo") + r"|turbopack", "Turborepo"),
        # Other runtimes
        (r"spring-boot|org\.springframework", "Spring Boot"),
        (r"dotnet\s+run|" + _token("aspnet"), "ASP.NET application"),
        (r"rails\s+(?:s|server)|" + _token("puma"), "Ruby on Rails"),
        (r"artisan\s+serve", "Laravel"),
        (r"php\s+-S", "PHP built-in server"),
        # Tooling
        (_token("ollama"), "Ollama"),
        (_token("localstack"), "LocalStack"),
        (_token("supabase"), "Supabase local"),
        (_token("firebase") + r".*emulator|emulators:", "Firebase emulator"),
        (_token("ngrok"), "ngrok tunnel"),
        (_token("cloudflared"), "Cloudflare tunnel"),
        (_token("vercel") + r"\s+dev", "Vercel dev server"),
        (_token("wrangler"), "Cloudflare Wrangler"),
        (_token("prisma") + r".*studio", "Prisma Studio"),
    ]
)


# ---------------------------------------------------------------------------
# Executable-name rules. Keys are lowercase basenames without directory.
# ---------------------------------------------------------------------------

NAME_RULES: Dict[str, str] = {
    # Databases and stores
    "postgres.exe": "PostgreSQL",
    "postgres": "PostgreSQL",
    "pg_ctl.exe": "PostgreSQL",
    "mysqld.exe": "MySQL",
    "mysqld": "MySQL",
    "mariadbd.exe": "MariaDB",
    "sqlservr.exe": "SQL Server",
    "mongod.exe": "MongoDB",
    "mongod": "MongoDB",
    "redis-server.exe": "Redis",
    "redis-server": "Redis",
    "redis.exe": "Redis",
    "memcached.exe": "Memcached",
    "influxd.exe": "InfluxDB",
    "clickhouse.exe": "ClickHouse",
    "cockroach.exe": "CockroachDB",
    "etcd.exe": "etcd",
    "minio.exe": "MinIO",
    "elasticsearch.exe": "Elasticsearch",
    "opensearch.exe": "OpenSearch",
    "qdrant.exe": "Qdrant",
    "weaviate.exe": "Weaviate",
    # Brokers / infra
    "rabbitmq-server.exe": "RabbitMQ",
    "nats-server.exe": "NATS",
    "zookeeper.exe": "ZooKeeper",
    "consul.exe": "Consul",
    "vault.exe": "HashiCorp Vault",
    # Web servers / proxies
    "nginx.exe": "nginx",
    "httpd.exe": "Apache HTTP Server",
    "apache.exe": "Apache HTTP Server",
    "caddy.exe": "Caddy",
    "traefik.exe": "Traefik",
    "haproxy.exe": "HAProxy",
    "iisexpress.exe": "IIS Express",
    "w3wp.exe": "IIS worker process",
    # Containers / VMs
    "docker.exe": "Docker",
    "dockerd.exe": "Docker daemon",
    "com.docker.backend.exe": "Docker Desktop",
    "com.docker.build.exe": "Docker Desktop",
    "docker desktop.exe": "Docker Desktop",
    "vpnkit.exe": "Docker networking",
    "wslrelay.exe": "WSL networking",
    "wslservice.exe": "WSL service",
    "vmmem.exe": "WSL / virtual machine",
    "vmware-hostd.exe": "VMware",
    "vboxheadless.exe": "VirtualBox",
    # AI / local models
    "ollama.exe": "Ollama",
    "ollama app.exe": "Ollama",
    "lm studio.exe": "LM Studio",
    "llama-server.exe": "llama.cpp server",
    # Editors and IDEs that open local ports
    "code.exe": "Visual Studio Code",
    "cursor.exe": "Cursor",
    "windsurf.exe": "Windsurf",
    "devenv.exe": "Visual Studio",
    "idea64.exe": "IntelliJ IDEA",
    "pycharm64.exe": "PyCharm",
    "webstorm64.exe": "WebStorm",
    "rider64.exe": "JetBrains Rider",
    "goland64.exe": "GoLand",
    "phpstorm64.exe": "PhpStorm",
    "clion64.exe": "CLion",
    "datagrip64.exe": "DataGrip",
    # Windows / system-ish
    "sshd.exe": "OpenSSH server",
    "spoolsv.exe": "Print Spooler",
    "mdnsresponder.exe": "Bonjour (mDNS)",
    "msedgewebview2.exe": "Edge WebView2",
    "svchost.exe": "Windows service host",
    "system": "Windows networking",
    "system idle process": "Windows kernel",
    "lsass.exe": "Windows security service",
    "services.exe": "Windows service control",
    "wininit.exe": "Windows startup process",
    "searchindexer.exe": "Windows Search",
    "sqlwriter.exe": "SQL Server VSS Writer",
    "msmpeng.exe": "Microsoft Defender",
    # Misc developer tooling
    "ngrok.exe": "ngrok tunnel",
    "cloudflared.exe": "Cloudflare tunnel",
    "adb.exe": "Android Debug Bridge",
    "gradle.exe": "Gradle daemon",
    "erl.exe": "Erlang runtime",
    "beam.smp.exe": "Erlang / Elixir runtime",
    "deno.exe": "Deno application",
    "bun.exe": "Bun application",
    "steam.exe": "Steam",
    "steamwebhelper.exe": "Steam",
    "spotify.exe": "Spotify",
}


# ---------------------------------------------------------------------------
# Port hints. Deliberately narrow: only ports whose meaning on Windows is
# effectively fixed, and only consulted when the process told us nothing.
# ---------------------------------------------------------------------------

PORT_HINTS: Dict[int, str] = {
    22: "SSH",
    25: "SMTP",
    53: "DNS",
    80: "HTTP",
    88: "Kerberos",
    135: "Windows RPC endpoint mapper",
    139: "NetBIOS session service",
    443: "HTTPS",
    445: "Windows file sharing (SMB)",
    465: "SMTP over TLS",
    587: "SMTP submission",
    623: "IPMI",
    993: "IMAP over TLS",
    995: "POP3 over TLS",
    1433: "SQL Server",
    1521: "Oracle Database",
    2375: "Docker daemon (unencrypted)",
    2376: "Docker daemon (TLS)",
    3306: "MySQL / MariaDB",
    3389: "Remote Desktop",
    5432: "PostgreSQL",
    5672: "RabbitMQ (AMQP)",
    5985: "Windows Remote Management",
    5986: "Windows Remote Management (TLS)",
    6379: "Redis",
    7680: "Windows Delivery Optimization",
    8009: "Apache JServ",
    9092: "Apache Kafka",
    9200: "Elasticsearch",
    11434: "Ollama",
    15672: "RabbitMQ management",
    27017: "MongoDB",
}


# Shared Windows host processes. For these the port number says far more than
# the executable name does, so the hint wins over the name rule.
GENERIC_HOSTS = frozenset(
    {
        "svchost.exe",
        "system",
        "system idle process",
        "lsass.exe",
        "services.exe",
        "wininit.exe",
        "dllhost.exe",
        "taskhostw.exe",
    }
)


# Generic runtime families, used as the final fallback.
FAMILY_RULES: Dict[str, str] = {
    "python.exe": "Python process",
    "pythonw.exe": "Python process",
    "python": "Python process",
    "python3.exe": "Python process",
    "python3": "Python process",
    "py.exe": "Python process",
    "conda.exe": "Python process",
    "node.exe": "Node.js process",
    "node": "Node.js process",
    "npm.exe": "Node.js process",
    "pnpm.exe": "Node.js process",
    "yarn.exe": "Node.js process",
    "bun.exe": "Bun process",
    "deno.exe": "Deno process",
    "java.exe": "Java application",
    "javaw.exe": "Java application",
    "dotnet.exe": ".NET application",
    "ruby.exe": "Ruby process",
    "php.exe": "PHP process",
    "go.exe": "Go process",
    "perl.exe": "Perl process",
    "rustc.exe": "Rust process",
    "cargo.exe": "Rust process",
    "powershell.exe": "PowerShell script",
    "pwsh.exe": "PowerShell script",
}


class DescriptionResolver:
    """Resolves a human description for a listening endpoint."""

    def __init__(self, custom_descriptions: Optional[Mapping[str, str]] = None) -> None:
        self._custom: Dict[str, str] = {}
        self.set_custom_descriptions(custom_descriptions or {})

    def set_custom_descriptions(self, mapping: Mapping[str, str]) -> None:
        cleaned: Dict[str, str] = {}
        for key, value in mapping.items():
            try:
                port = int(str(key).strip())
            except (TypeError, ValueError):
                continue
            if isinstance(value, str) and value.strip():
                cleaned[str(port)] = value.strip()
        self._custom = cleaned

    @property
    def custom_descriptions(self) -> Dict[str, str]:
        return dict(self._custom)

    def custom_for(self, port: int) -> Optional[str]:
        return self._custom.get(str(port))

    def resolve(self, port: int, info: ProcessInfo) -> str:
        """Best available description for ``port`` owned by ``info``."""
        custom = self.custom_for(port)
        if custom:
            return custom

        automatic = self.resolve_automatic(port, info)
        return automatic

    def resolve_automatic(self, port: int, info: ProcessInfo) -> str:
        """The description we would show with no user configuration."""
        name = self._basename(info.name) or self._basename(info.exe)

        # 2. Command line — the strongest automatic evidence.
        if info.cmdline:
            for pattern, label in CMDLINE_RULES:
                if pattern.search(info.cmdline):
                    return label

        hint = PORT_HINTS.get(port)

        # A shared host process tells us nothing; the port tells us everything.
        if name in GENERIC_HOSTS and hint:
            return hint

        # 3. Executable name.
        if name:
            mapped = NAME_RULES.get(name)
            if mapped:
                return mapped

        # 4. Port hint, only when the process itself is uninformative.
        family = FAMILY_RULES.get(name) if name else None
        if hint and family is None:
            return hint

        # 5. Generic family, then honest ignorance.
        if family:
            return family

        if info.pid > 0 and not info.exists:
            return "Process no longer running"
        if info.pid > 0 and not info.accessible and not name:
            return "Access restricted"
        return UNKNOWN

    @staticmethod
    def _basename(value: Optional[str]) -> str:
        if not value:
            return ""
        cleaned = value.strip().strip('"')
        cleaned = cleaned.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        return cleaned.lower()
