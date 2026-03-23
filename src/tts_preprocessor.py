"""
TTS Text Preprocessor — normalizes text for natural-sounding speech synthesis.

Handles:
  - Tech abbreviations (API, GPU, CPU, HTML, URL, etc.)
  - Programming symbols (@, #, /, ->, =>, etc.)
  - Numbers with units (32GB, 85%, $29.99, 3.14)
  - File paths (src/web.py → "source slash web dot pie")
  - Keyboard shortcuts (Ctrl+Shift+P)
  - Code syntax (removed or verbalized)
  - URLs (simplified)
  - Markdown formatting (stripped)
  - Punctuation for proper pauses
  - Emoji conversion
"""
import re


# ── Abbreviation dictionary ──────────────────────────────────
ABBREVIATIONS = {
    # Tech
    "API": "A P I", "APIs": "A P Is", "GPU": "G P U", "GPUs": "G P Us",
    "CPU": "C P U", "CPUs": "C P Us", "RAM": "ram", "ROM": "rom",
    "SSD": "S S D", "HDD": "H D D", "NVMe": "N V M E",
    "USB": "U S B", "HDMI": "H D M I", "DNS": "D N S",
    "TCP": "T C P", "UDP": "U D P", "HTTP": "H T T P", "HTTPS": "H T T P S",
    "SSH": "S S H", "SSL": "S S L", "TLS": "T L S",
    "IP": "I P", "URL": "U R L", "URLs": "U R Ls", "URI": "U R I",
    "HTML": "H T M L", "CSS": "C S S", "JS": "javascript", "JSON": "jason",
    "XML": "X M L", "YAML": "yamel", "SQL": "sequel", "NoSQL": "no sequel",
    "AWS": "A W S", "GCP": "G C P", "CLI": "C L I", "GUI": "gooey",
    "IDE": "I D E", "SDK": "S D K", "JDK": "J D K", "JVM": "J V M",
    "VM": "V M", "VMs": "V Ms", "OS": "O S", "WSL": "W S L",
    "VRAM": "V ram", "NPU": "N P U", "TPU": "T P U",
    "LLM": "L L M", "LLMs": "L L Ms", "AI": "A I", "ML": "M L",
    "NLP": "N L P", "OCR": "O C R", "TTS": "T T S", "STT": "S T T",
    "RLHF": "R L H F", "GPT": "G P T", "LLaMA": "lama",
    "ONNX": "onyx", "GGUF": "G goof", "CUDA": "kooda",
    # Common
    "FAQ": "F A Q", "ASAP": "A sap", "ETA": "E T A",
    "FYI": "F Y I", "DIY": "D I Y", "PDF": "P D F",
    "CEO": "C E O", "CTO": "C T O", "VP": "V P",
    "PR": "P R", "PRs": "P Rs", "CI": "C I", "CD": "C D",
    "QA": "Q A", "UI": "U I", "UX": "U X",
    "DB": "database", "DBMS": "database management system",
    "OOM": "out of memory", "OOP": "O O P",
    "CORS": "cores", "CSRF": "C surf", "XSS": "cross site scripting",
    "SSRF": "S S R F", "OWASP": "oh wasp",
    "OAuth": "oh auth", "JWT": "J W T",
    "FIFO": "fife oh", "LIFO": "life oh",
    "CRUD": "crud", "REST": "rest", "gRPC": "G R P C",
    "SSE": "S S E", "WebSocket": "web socket",
    "npm": "N P M", "pip": "pip", "apt": "apt",
    "git": "git", "GitHub": "git hub", "GitLab": "git lab",
    "Docker": "docker", "Kubernetes": "koo ber net ees", "k8s": "kates",
    "regex": "rej ex", "RegEx": "rej ex",
    "localhost": "local host",
    "OmniAgent": "omni agent",
    # Units
    "MHz": "megahertz", "GHz": "gigahertz", "kHz": "kilohertz",
    "Mbps": "megabits per second", "Gbps": "gigabits per second",
    "fps": "frames per second",
}

# ── Symbol mappings ──────────────────────────────────────────
SYMBOLS = {
    "→": " to ", "←": " from ", "↑": " up ", "↓": " down ",
    "=>": " arrow ", "->": " arrow ", "<-": " from ",
    "!=": " not equal to ", "==": " equals ", "===": " strict equals ",
    ">=": " greater than or equal to ", "<=": " less than or equal to ",
    "&&": " and ", "||": " or ",
    "++": " plus plus ", "--": " minus minus ",
    "**": " double star ",
    "~": " tilde ", "`": "", "```": "",
    "•": ", ", "·": ", ",
    "✓": " check ", "✗": " cross ", "✅": " check ", "❌": " cross ",
    "⚡": " lightning ", "🔥": " fire ", "🚀": " rocket ",
    "⚠": " warning ", "💡": " idea ",
}

# ── Emoji to words ───────────────────────────────────────────
EMOJI_MAP = {
    "😀": "", "😂": "", "🤔": "", "👍": " thumbs up ",
    "👎": " thumbs down ", "❤️": " heart ", "🎉": " celebration ",
    "📊": "", "📈": "", "📉": "", "🔧": "", "🔨": "", "⚙️": "",
    "📁": "", "📂": "", "📄": "", "🗑": "", "🔍": "",
    "💬": "", "🔗": "", "🖥": "", "📱": "",
}


def preprocess_for_tts(text: str) -> str:
    """Transform text into speech-friendly format."""
    if not text:
        return text

    # Step 1: Remove markdown formatting
    text = _strip_markdown(text)

    # Step 2: Remove code blocks entirely (not speakable)
    text = re.sub(r'```[\s\S]*?```', ' code block omitted. ', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)  # Keep inline code content

    # Step 3: Convert emojis
    for emoji, word in EMOJI_MAP.items():
        text = text.replace(emoji, word)

    # Step 4: Convert symbols
    for sym, word in SYMBOLS.items():
        text = text.replace(sym, word)

    # Step 5: Handle URLs — simplify to domain
    text = re.sub(
        r'https?://([a-zA-Z0-9.-]+)(/[^\s]*)?',
        lambda m: f"{m.group(1).replace('.', ' dot ')}",
        text
    )

    # Step 6: Handle file paths (must have at least 2 path components with a dot extension)
    text = re.sub(
        r'(?<!\w)([a-zA-Z][a-zA-Z0-9_]*/[a-zA-Z][a-zA-Z0-9_./]*\.[a-zA-Z]{1,5})\b',
        lambda m: _verbalize_path(m.group(1)),
        text
    )

    # Step 7: Handle keyboard shortcuts (Ctrl+Shift+P → "control shift P")
    text = re.sub(r'Ctrl\+', 'control ', text)
    text = re.sub(r'Shift\+', 'shift ', text)
    text = re.sub(r'Alt\+', 'alt ', text)
    text = re.sub(r'Cmd\+', 'command ', text)
    text = re.sub(r'Meta\+', 'meta ', text)

    # Step 8: Handle slash-based patterns FIRST (before / gets stripped)
    text = re.sub(r'(\d+)\s*tok/s', r'\1 tokens per second', text)
    text = re.sub(r'\$(\d+[\d,.]*)/mo', lambda m: f"{_verbalize_money(m.group(1))} dollars per month", text)
    text = re.sub(r'/mo\b', ' per month', text)
    text = re.sub(r'/yr\b', ' per year', text)
    text = re.sub(r'w/o\b', 'without', text)
    text = re.sub(r'\bw/', 'with ', text)
    text = re.sub(r'(\d+)/(\d+)\s*GB', r'\1 of \2 gigabytes', text)
    text = re.sub(r'(\d+)/(\d+)\s*MB', r'\1 of \2 megabytes', text)
    text = re.sub(r'(\d+)/(\d+)', r'\1 of \2', text)

    # Step 9: Numbers with units
    text = re.sub(r'(\d+)°([CF])', lambda m: f"{m.group(1)} degrees {'celsius' if m.group(2)=='C' else 'fahrenheit'}", text)
    text = re.sub(r'(\d+)%', r'\1 percent', text)
    text = re.sub(r'\$(\d+[\d,.]*)', lambda m: f"{_verbalize_money(m.group(1))} dollars", text)
    text = re.sub(r'(\d+)\s*GB', r'\1 gigabytes', text)
    text = re.sub(r'(\d+)\s*MB', r'\1 megabytes', text)
    text = re.sub(r'(\d+)\s*KB', r'\1 kilobytes', text)
    text = re.sub(r'(\d+)\s*TB', r'\1 terabytes', text)
    text = re.sub(r'(\d+)\s*ms\b', r'\1 milliseconds', text)
    text = re.sub(r'(\d+)\s*fps\b', r'\1 frames per second', text)

    # Step 10: Version numbers, hashtags, abbreviations
    text = re.sub(r'\bv(\d+)\.(\d+)', r'version \1 point \2', text)
    text = re.sub(r'\bv(\d+)\b', r'version \1', text)
    text = re.sub(r'#(\d+)', r'number \1', text)
    text = re.sub(r'e\.g\.', 'for example', text)
    text = re.sub(r'i\.e\.', 'that is', text)
    text = re.sub(r'etc\.', 'etcetera', text)
    text = re.sub(r'\bvs\.?\b', 'versus', text)

    # Step 11: Expand abbreviations (case-sensitive, whole words only)
    for abbr, expansion in ABBREVIATIONS.items():
        text = re.sub(r'\b' + re.escape(abbr) + r'\b', expansion, text)

    # Step 12: Handle remaining special characters
    text = text.replace('@', ' at ')
    text = text.replace('&', ' and ')
    text = text.replace('+', ' plus ')
    text = text.replace('=', ' equals ')
    text = text.replace('<', ' less than ')
    text = text.replace('>', ' greater than ')
    text = text.replace('|', ' ')
    text = text.replace('{', '').replace('}', '')
    text = text.replace('[', '').replace(']', '')
    text = text.replace('(', ', ').replace(')', ', ')
    text = text.replace('_', ' ')

    # Step 13: Clean up
    text = re.sub(r'\s*[,;]\s*[,;]+', ',', text)  # Multiple commas
    text = re.sub(r'\s+', ' ', text)  # Collapse whitespace
    text = re.sub(r'\s+([.,!?;:])', r'\1', text)  # Space before punctuation
    text = re.sub(r'([.!?])\s*([.!?])+', r'\1', text)  # Multiple sentence endings
    text = text.strip()

    # Step 14: Add natural pauses (periods → slight pause)
    text = re.sub(r'\.\s+', '. ', text)

    return text


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting, keeping the text content."""
    # Headers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Bold/italic
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)
    # Links [text](url) → text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Images ![alt](url) → ""
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', '', text)
    # Horizontal rules
    text = re.sub(r'^---+\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\*\*\*+\s*$', '', text, flags=re.MULTILINE)
    # List markers
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    # Blockquotes
    text = re.sub(r'^\s*>\s?', '', text, flags=re.MULTILINE)
    # Tables (simplify)
    text = re.sub(r'\|', ', ', text)
    text = re.sub(r'^[-:]+\s*$', '', text, flags=re.MULTILINE)
    return text


def _verbalize_path(path: str) -> str:
    """Convert a file path to speech: src/web.py → source, web dot pie"""
    parts = path.split('/')
    spoken = []
    for p in parts:
        if '.' in p and not p.startswith('.'):
            name, ext = p.rsplit('.', 1)
            ext_words = {
                'py': 'pie', 'js': 'javascript', 'ts': 'typescript',
                'kt': 'kotlin', 'java': 'java', 'rs': 'rust',
                'go': 'go', 'rb': 'ruby', 'sh': 'shell',
                'json': 'jason', 'yaml': 'yaml', 'yml': 'yaml',
                'md': 'markdown', 'txt': 'text', 'csv': 'C S V',
                'html': 'H T M L', 'css': 'C S S', 'xml': 'X M L',
                'sql': 'sequel', 'db': 'database',
                'png': 'P N G', 'jpg': 'jpeg', 'gif': 'gif',
                'wav': 'wave', 'mp3': 'M P 3', 'mp4': 'M P 4',
                'pdf': 'P D F', 'zip': 'zip', 'tar': 'tar',
                'gz': 'G Z', 'log': 'log', 'env': 'env',
                'toml': 'toml', 'cfg': 'config', 'ini': 'I N I',
            }
            ext_spoken = ext_words.get(ext, ext)
            spoken.append(f"{name} dot {ext_spoken}")
        else:
            word_map = {
                'src': 'source', 'lib': 'lib', 'bin': 'bin',
                'etc': 'etcetera', 'var': 'var', 'tmp': 'temp',
                'usr': 'user', 'dev': 'dev', 'api': 'A P I',
                'ui': 'U I', 'app': 'app', 'pkg': 'package',
                'cmd': 'command', 'cfg': 'config', 'img': 'image',
                'docs': 'docs', 'test': 'test', 'tests': 'tests',
            }
            spoken.append(word_map.get(p.lower(), p))
    return ', '.join(spoken)


def _verbalize_money(amount: str) -> str:
    """Convert money amount to spoken form: 29.99 → twenty nine ninety nine"""
    amount = amount.replace(',', '')
    if '.' in amount:
        dollars, cents = amount.split('.', 1)
        if cents == '00':
            return dollars
        return f"{dollars} {cents}"
    return amount
