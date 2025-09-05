#!/bin/bash
# Warp Account Manager Launcher - macOS Edition
# Automatic installation and startup script

# Colors for better output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Clear screen and show header
clear
echo
echo "===================================================="
echo "   Warp Account Manager - Automatic Installation"
echo "===================================================="
echo

# Function to print status messages
print_status() {
    echo -e "${GREEN}[OK]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Navigate to script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

# Check if running as root (administrator equivalent)
echo "[1/6] Checking permissions..."
if [[ $EUID -eq 0 ]]; then
    print_warning "Running as root - this is not recommended for this application"
    print_info "You may run this script as a regular user"
else
    print_status "Running as regular user"
fi
echo

# Check if Python is installed
echo "[2/6] Checking Python installation..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
    print_status "Python $PYTHON_VERSION found"
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_VERSION=$(python --version 2>&1 | cut -d' ' -f2)
    # Check if it's Python 3
    if python -c "import sys; exit(0 if sys.version_info[0] >= 3 else 1)" 2>/dev/null; then
        print_status "Python $PYTHON_VERSION found"
        PYTHON_CMD="python"
    else
        print_error "Python 3.8 or higher is required, but found Python 2"
        echo
        echo "Please install Python 3 using one of these methods:"
        echo "1. Homebrew: brew install python3"
        echo "2. Python.org: https://python.org"
        echo "3. Pyenv: pyenv install 3.11"
        echo
        read -p "Press Enter to exit..."
        exit 1
    fi
else
    print_error "Python not found!"
    echo
    echo "Python 3.8 or higher is required."
    echo "Please install Python using one of these methods:"
    echo "1. Homebrew: brew install python3"
    echo "2. Python.org: https://python.org"
    echo "3. Pyenv: pyenv install 3.11"
    echo
    read -p "Press Enter to exit..."
    exit 1
fi
echo

# Check if pip is installed
echo "[3/6] Checking pip installation..."
if command -v pip3 &> /dev/null; then
    print_status "pip3 found"
    PIP_CMD="pip3"
elif command -v pip &> /dev/null; then
    print_status "pip found"
    PIP_CMD="pip"
else
    print_error "pip not found!"
    echo
    echo "pip should come with Python."
    echo "Try reinstalling Python or install pip manually:"
    echo "curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py"
    echo "$PYTHON_CMD get-pip.py"
    echo
    read -p "Press Enter to exit..."
    exit 1
fi
echo

# Check and install required packages
echo "[4/6] Checking required Python packages..."
echo

# Package list
PACKAGES=("PyQt5" "requests" "mitmproxy" "psutil")

# Check each package
for package in "${PACKAGES[@]}"; do
    echo "  Checking: $package"
    if $PIP_CMD show "$package" > /dev/null 2>&1; then
        print_status "  $package already installed"
    else
        print_info "  [MISSING] Installing $package..."
        
        # Try different installation methods for macOS
        if [[ "$package" == "PyQt5" ]]; then
            # PyQt5 via Homebrew on macOS
            if command -v brew &> /dev/null; then
                echo "  Trying Homebrew installation for PyQt5..."
                if brew install pyqt@5; then
                    print_status "  $package successfully installed via Homebrew"
                    continue
                fi
            fi
        elif [[ "$package" == "mitmproxy" ]]; then
            # mitmproxy via Homebrew (already should be installed)
            if command -v mitmdump &> /dev/null; then
                print_status "  mitmproxy already available via Homebrew"
                continue
            fi
        fi
        
        # Try pip with --break-system-packages as fallback
        if $PIP_CMD install "$package" --break-system-packages; then
            print_status "  $package successfully installed"
        else
            print_error "  Failed to install $package!"
            echo
            echo "  Possible solutions:"
            echo "  1. Install via Homebrew: brew install $package"
            echo "  2. Create virtual environment"
            echo "  3. Try: $PIP_CMD install --user $package --break-system-packages"
            echo
            read -p "Continue anyway? (y/N): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
    fi
done

echo
print_status "All required packages are ready"
echo

# Database file check
echo "[5/6] Checking database file..."
if [[ -f "accounts.db" ]]; then
    print_status "Database file exists"
else
    print_info "Database file will be created"
fi
echo

# Start Warp Account Manager
echo "[6/6] Starting Warp Account Manager..."
echo
echo "===================================================="
echo "   Installation completed - Starting application"
echo "===================================================="
echo

if [[ -f "warp_account_manager.py" ]]; then
    print_info "Opening Warp Account Manager..."
    echo
    print_warning "NOTE: Do not close this terminal window! This console window"
    print_warning "      must remain open while the application is running."
    echo
    
    # Start the application
    $PYTHON_CMD warp_account_manager.py
    
    echo
    print_info "Warp Account Manager closed."
else
    print_error "warp_account_manager.py file not found!"
    echo
    echo "Current directory: $(pwd)"
    echo "Script directory: $SCRIPT_DIR"
    echo
    echo "Please ensure all files are in the correct location."
fi

echo
echo "Press Enter to exit..."
read