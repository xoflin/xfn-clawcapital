#!/bin/bash
# ClawCapital — First-time setup on Ubuntu (GCP VM)
# Run once as the ubuntu user: bash deploy/setup.sh

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "=== ClawCapital Setup ==="
echo "Repo: $REPO_DIR"

# 1. Python 3.12+
echo ""
echo "[1/5] Checking Python version..."
python3 --version
PYTHON_OK=$(python3 -c "import sys; print(sys.version_info >= (3,12))")
if [ "$PYTHON_OK" != "True" ]; then
  echo "Python 3.12+ required. Installing..."
  sudo add-apt-repository ppa:deadsnakes/ppa -y
  sudo apt-get update -y
  sudo apt-get install -y python3.12 python3.12-venv python3.12-dev
  PYTHON_BIN="python3.12"
else
  PYTHON_BIN="python3"
fi

# 2. Virtual environment
echo ""
echo "[2/5] Creating virtual environment..."
$PYTHON_BIN -m venv "$REPO_DIR/.venv"
source "$REPO_DIR/.venv/bin/activate"

# 3. Dependencies
echo ""
echo "[3/5] Installing dependencies..."
pip install --upgrade pip
pip install -r "$REPO_DIR/requirements.txt"

# 4. .env
echo ""
echo "[4/5] Checking .env..."
if [ ! -f "$REPO_DIR/.env" ]; then
  cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
  echo "  .env criado a partir de .env.example"
  echo "  !! Edita $REPO_DIR/.env com as tuas API keys antes de continuar !!"
  echo "     nano $REPO_DIR/.env"
else
  echo "  .env já existe — ok"
fi

# 5. Systemd service
echo ""
echo "[5/5] Installing systemd service..."
sudo cp "$REPO_DIR/deploy/clawcapital.service" /etc/systemd/system/clawcapital.service
sudo sed -i "s|/home/ubuntu/xfn-clawcapital|$REPO_DIR|g" /etc/systemd/system/clawcapital.service
sudo systemctl daemon-reload
sudo systemctl enable clawcapital

# Log file permissions
sudo touch /var/log/clawcapital.log
sudo chown ubuntu:ubuntu /var/log/clawcapital.log

echo ""
echo "=== Setup completo ==="
echo ""
echo "Próximos passos:"
echo "  1. Editar .env:         nano $REPO_DIR/.env"
echo "  2. Testar ciclo único:  source $REPO_DIR/.venv/bin/activate && python $REPO_DIR/main.py --skip-heartbeat"
echo "  3. Iniciar serviço:     sudo systemctl start clawcapital"
echo "  4. Ver logs:            tail -f /var/log/clawcapital.log"
echo "  5. Estado do serviço:   sudo systemctl status clawcapital"
