#!/usr/bin/env bash
# ==============================================================================
# ytstr — Single-Script Universal Installer
# One-line install:
#   curl -fsSL https://raw.githubusercontent.com/seeramsujay/ytstr/master/install.sh | bash
# ==============================================================================

set -e

# Terminal Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${BOLD}${CYAN}"
echo "  __   ___       __  "
echo "  \ \ / / |_ ___| |_ _ __ "
echo "   \ V /| __/ __| __| '__|"
echo "    | | | |_\__ \ |_| |   "
echo "    |_|  \__|___/\__|_|   "
echo -e "${NC}"
echo -e "${BOLD}Installing ytstr — High-Speed CLI & GUI YouTube Music Streamer${NC}\n"

# 1. Check System Dependencies (mpv, ffmpeg)
MISSING_DEPS=""
command -v mpv >/dev/null 2>&1 || MISSING_DEPS="$MISSING_DEPS mpv"
command -v ffmpeg >/dev/null 2>&1 || MISSING_DEPS="$MISSING_DEPS ffmpeg"

if [ -n "$MISSING_DEPS" ]; then
    echo -e "${YELLOW}Warning: Missing required system audio decoders:${MISSING_DEPS}${NC}"
    echo -e "Please install them via your package manager:"
    if command -v apt >/dev/null 2>&1; then
        echo -e "  ${CYAN}sudo apt update && sudo apt install -y mpv ffmpeg${NC}"
    elif command -v pacman >/dev/null 2>&1; then
        echo -e "  ${CYAN}sudo pacman -S mpv ffmpeg${NC}"
    elif command -v dnf >/dev/null 2>&1; then
        echo -e "  ${CYAN}sudo dnf install -y mpv ffmpeg${NC}"
    elif command -v brew >/dev/null 2>&1; then
        echo -e "  ${CYAN}brew install mpv ffmpeg${NC}"
    fi
    echo ""
fi

# 2. Ensure `uv` is installed
export PATH="$HOME/.local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
    echo -e "${CYAN}→ Installing uv (lightning-fast Python package installer)...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v uv >/dev/null 2>&1; then
    echo -e "${RED}Error: Failed to install or locate uv in ~/.local/bin.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ uv detected:${NC} $(uv --version)"

# 3. Determine Source Directory (Local or Remote Clone)
INSTALL_DIR="$HOME/.local/share/ytstr"
REPO_URL="https://github.com/seeramsujay/ytstr.git"

if [ -f "./pyproject.toml" ] && [ -d "./src/ytstr" ]; then
    SOURCE_DIR="$(pwd)"
    echo -e "${CYAN}→ Installing from current local repository: ${SOURCE_DIR}${NC}"
else
    echo -e "${CYAN}→ Setting up repository at ${INSTALL_DIR}...${NC}"
    mkdir -p "$HOME/.local/share"
    if [ -d "$INSTALL_DIR/.git" ]; then
        echo -e "${CYAN}→ Updating existing repository...${NC}"
        git -C "$INSTALL_DIR" pull --quiet
    else
        echo -e "${CYAN}→ Cloning repository...${NC}"
        git clone --quiet "$REPO_URL" "$INSTALL_DIR"
    fi
    SOURCE_DIR="$INSTALL_DIR"
fi

# 4. Sync Virtual Environment via uv
echo -e "${CYAN}→ Building virtual environment and installing dependencies...${NC}"
cd "$SOURCE_DIR"
uv sync --quiet --extra media-keys

# 5. Create Standalone CLI and GUI Launchers in ~/.local/bin
mkdir -p "$HOME/.local/bin"

# CLI launcher
cat << 'EOF' > "$HOME/.local/bin/ytstr"
#!/usr/bin/env bash
exec uv --directory "$SOURCE_DIR_PLACEHOLDER" run ytstr "$@"
EOF
sed -i "s|\$SOURCE_DIR_PLACEHOLDER|$SOURCE_DIR|g" "$HOME/.local/bin/ytstr"
chmod +x "$HOME/.local/bin/ytstr"

# GUI launcher
cat << 'EOF' > "$HOME/.local/bin/ytstr-gui"
#!/usr/bin/env bash
exec uv --directory "$SOURCE_DIR_PLACEHOLDER" run ytstr-gui "$@"
EOF
sed -i "s|\$SOURCE_DIR_PLACEHOLDER|$SOURCE_DIR|g" "$HOME/.local/bin/ytstr-gui"
chmod +x "$HOME/.local/bin/ytstr-gui"

# 6. Verify Installation
echo -e "${GREEN}✓ Executables installed to ~/.local/bin/ytstr and ~/.local/bin/ytstr-gui${NC}"

# Shell PATH warning if ~/.local/bin not in PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo -e "${YELLOW}Note: Add ~/.local/bin to your PATH in ~/.bashrc or ~/.zshrc:${NC}"
    echo -e "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

echo -e "\n${BOLD}${GREEN}Installation Complete!${NC}"
echo -e "──────────────────────────────────────────────────────"
echo -e "  ${BOLD}Run ytstr CLI:${NC}          ytstr \"lofi hip hop\" --no-mix"
echo -e "  ${BOLD}Run Direct Stream:${NC}      ytstr \"synthwave mix\" --stream"
echo -e "  ${BOLD}Run Auto-DJ:${NC}            ytstr \"techno playlist\""
echo -e "  ${BOLD}Launch Desktop GUI:${NC}     ytstr-gui  (or ytstr --gui)"
echo -e "──────────────────────────────────────────────────────\n"
