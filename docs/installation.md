# Installation Guide

## System Requirements
- Python 3.11 or higher
- Linux (e.g. Fedora, Ubuntu, Debian), macOS, or Windows WSL2
- AWS CLI configured (optional, but recommended for SSO and profile management)

## Recommended Installation (Virtual Environment)

```bash
# Clone the repository
git clone https://github.com/example/ec2kit.git
cd ec2kit

# Create and activate a Python virtual environment
python3 -m venv venv
source venv/bin/activate

# Install in editable mode with development dependencies
pip install -e ".[dev]"
```

## Fedora Setup Guide

On Fedora 39/40/41/42/43:

```bash
# Install system Python and development tools
sudo dnf install -y python3 python3-pip git

# Set up local virtual environment
python3 -m venv ~/.venvs/ec2kit
source ~/.venvs/ec2kit/bin/activate

# Install ec2kit
pip install -e .

# Add to PATH (e.g. in ~/.bashrc)
echo 'export PATH="$HOME/.venvs/ec2kit/bin:$PATH"' >> ~/.bashrc
```

## Verifying Installation

Run the CLI help and version checks:

```bash
ec2kit --help
ec2kit --version
ec2kit info
```
