#!/bin/bash
# ─────────────────────────────────────────────────────
# LIC DSF Assessment Tool — Launch Script
# ─────────────────────────────────────────────────────

PYTHON="/opt/homebrew/bin/python3.11"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "================================================================"
echo "  LIC DSF Assessment Tool"
echo "  IMF/World Bank 2017 Revised Framework"
echo "================================================================"
echo "  Script dir: $SCRIPT_DIR"
echo ""

# Check Python
if ! command -v "$PYTHON" &>/dev/null; then
    PYTHON="python3"
fi

# Check streamlit
if ! "$PYTHON" -c "import streamlit" &>/dev/null; then
    echo "Installing requirements..."
    "$PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt" --quiet
fi

echo "  Starting Streamlit app..."
echo "  → Open http://localhost:8501 in your browser"
echo "  → Press Ctrl+C to stop"
echo ""

cd "$SCRIPT_DIR"
"$PYTHON" -m streamlit run app.py \
    --server.headless true \
    --server.port 8501 \
    --browser.gatherUsageStats false \
    --server.maxUploadSize 50
