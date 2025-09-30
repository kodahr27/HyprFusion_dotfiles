#!/bin/bash

# --- Helper Functions ---

# Checks for Internet connectivity
check_internet() {
  if ! ping -c 1 archlinux.org &>/dev/null; then
    echo "No internet connection detected. Please connect and retry."
    exit 1
  fi
}

# Checks if command is available
command_exists() {
  command -v "$1" >/dev/null 2>&1
}

# Safe package installer with retry logic
install_pkg() {
  local pkg="$1"
  local retries=6
  local delay=10

  for ((i=1; i<=retries; i++)); do
    echo "Attempt $i of $retries: Installing $pkg..."
    
    # Capture both stdout and stderr
    local output
    output=$(yay -S --noconfirm --needed "$pkg" 2>&1)
    local exit_code=$?
    
    # Check if package was not found
    if echo "$output" | grep -qi -E "(package.*not found|target not found|no packages match|unable to find|could not find any packages|No AUR package)"; then
      echo "❌ Package $pkg not found in repositories."
      while true; do
        read -rp "Package '$pkg' not found. Do you want to (s)kip this package, (r)etry installation, or (a)bort script? [s/r/a]: " choice
        choice=${choice,,}
        case $choice in
          s|skip)
            echo "⚠️ Skipping $pkg - package not found."
            return 0
            ;;
          r|retry)
            echo "🔄 Retrying search for $pkg..."
            break  # break inner while loop to retry
            ;;
          a|abort)
            echo "❌ Aborting script as requested."
            exit 1
            ;;
          *)
            echo "Invalid choice. Please enter 's' to skip, 'r' to retry, or 'a' to abort."
            ;;
        esac
      done
      # If we get here, user chose retry, so continue the outer loop
      if (( i < retries )); then
        yay -Sy --noconfirm >/dev/null 2>&1 || true
      fi
      continue
    fi
    
    # Check for successful installation
    if [[ $exit_code -eq 0 ]] && ! echo "$output" | grep -qi "error"; then
      echo "✅ $pkg installed successfully."
      return 0
    fi

    echo "❌ Failed to install $pkg (attempt $i/$retries)."
    if (( i < retries )); then
      echo "Waiting ${delay}s before retry..."
      sleep "$delay"
      # Refresh databases on retry to handle transient issues
      yay -Sy --noconfirm >/dev/null 2>&1 || true
    fi
  done

  # After all retries failed for other reasons
  echo "❌ ERROR: Could not install $pkg after $retries attempts."
  while true; do
    read -rp "Do you want to (s)kip this package, (r)etry installation, or (a)bort script? [s/r/a]: " choice
    choice=${choice,,}
    case $choice in
      s|skip)
        echo "⚠️ Skipping $pkg - you may need to install it manually later."
        return 0
        ;;
      r|retry)
        echo "🔄 Retrying installation of $pkg..."
        install_pkg "$pkg"
        return $?
        ;;
      a|abort)
        echo "❌ Aborting script as requested."
        exit 1
        ;;
      *)
        echo "Invalid choice. Please enter 's' to skip, 'r' to retry, or 'a' to abort."
        ;;
    esac
  done
}

# --- Script Start ---

# Check network before doing anything
#check_internet

# Early pacman.conf & ghostmirror mirrorlist check and fix BEFORE doing anything else
USER_HOME=$(eval echo "~$USER")
GHOSTMIRROR_MIRRORLIST="$USER_HOME/.config/ghostmirror/mirrorlist"
PACMAN_CONF="/etc/pacman.conf"
if grep -q "ghostmirror/mirrorlist" "$PACMAN_CONF" && [ ! -f "$GHOSTMIRROR_MIRRORLIST" ]; then
  echo "Pacman is set to use ghostmirror mirrorlist, but it doesn't exist -- restoring default..."
  sudo sed -i "s|Include = $GHOSTMIRROR_MIRRORLIST|Include = /etc/pacman.d/mirrorlist|g" "$PACMAN_CONF"
fi

# Ask user for configuration choices
read -rp "Do you want to perform the miscellaneous Hyprland plugin setup? (y/N): " perform_misc
perform_misc=${perform_misc,,}  # convert to lowercase
read -r -p "Do you want to install and setup ghostmirror for mirror optimization? (y/N) " answer
answer=${answer,,}  # convert to lowercase

# --- Pacman config optimizations ---
echo "Optimizing pacman configuration..."
sudo sed -i 's/^#ParallelDownloads = 5/ParallelDownloads = 5/' /etc/pacman.conf

# Ensure yay exists, install if missing
if ! command_exists yay; then
  echo "yay not found, installing yay..."
  sudo pacman -Sy --needed --noconfirm git base-devel
  temp_dir=$(mktemp -d)
  git clone https://aur.archlinux.org/yay.git "$temp_dir/yay"
  cd "$temp_dir/yay" || exit 1
  makepkg -si --noconfirm
  cd - >/dev/null || exit 1
  rm -rf "$temp_dir"
else
  echo "yay is already installed."
fi

# --- Ghostmirror setup (safe sequence) ---
if [[ "$answer" == "y" || "$answer" == "yes" ]]; then
  echo "Installing and setting up ghostmirror..."
  if ! pacman -Qi ghostmirror >/dev/null 2>&1 && ! command_exists ghostmirror; then
    install_pkg ghostmirror
  fi
  mkdir -p "$USER_HOME/.config/ghostmirror"
  # Create a valid initial mirrorlist if it doesn't exist
  if [ ! -f "$GHOSTMIRROR_MIRRORLIST" ]; then
    echo "Generating initial mirrorlist with ghostmirror..."
    ghostmirror -PoclLS Italy,Germany,France "$GHOSTMIRROR_MIRRORLIST" 30 state,outofdate,morerecent,ping || {
      echo "Failed to generate initial mirrorlist. Aborting setup."
      exit 1
    }
  fi
  echo "Backing up $PACMAN_CONF..."
  sudo cp "$PACMAN_CONF" "$PACMAN_CONF.bak"
  if ! grep -q "Include = $GHOSTMIRROR_MIRRORLIST" "$PACMAN_CONF"; then
    echo "Modifying $PACMAN_CONF to point 'Include' lines to ghostmirror mirrorlist..."
    sudo sed -i -E "s|Include = /etc/pacman.d/mirrorlist|Include = $GHOSTMIRROR_MIRRORLIST|g" "$PACMAN_CONF"
  else
    echo "$PACMAN_CONF already uses the ghostmirror mirrorlist path, skipping modification."
  fi
  USERNAME=$(whoami)
  echo "Enabling systemd linger for user $USERNAME..."
  sudo loginctl enable-linger "$USERNAME"

  # only run as user if script is executed as root (installer context)
  if [ "$EUID" -eq 0 ]; then
    sudo -u "$USERNAME" --preserve-env=XDG_RUNTIME_DIR,DBUS_SESSION_BUS_ADDRESS \
      bash -lc "ghostmirror -DPo -mul \"$GHOSTMIRROR_MIRRORLIST\" \"$GHOSTMIRROR_MIRRORLIST\" -s light -S state,outofdate,morerecent,speed && \
               echo 'Checking for ghostmirror.timer...' && \
               if systemctl --user list-unit-files ghostmirror.timer >/dev/null 2>&1; then \
                 echo 'Timer unit found, enabling and starting...' && \
                 systemctl --user enable ghostmirror.timer && \
                 systemctl --user start ghostmirror.timer; \
               else \
                 echo 'Warning: ghostmirror.timer unit not found. Trying to reload systemd user daemon...' && \
                 systemctl --user daemon-reload && \
                 if systemctl --user list-unit-files ghostmirror.timer >/dev/null 2>&1; then \
                   echo 'Timer unit found after reload, enabling and starting...' && \
                   systemctl --user enable ghostmirror.timer && \
                   systemctl --user start ghostmirror.timer; \
                 else \
                   echo 'Timer unit still not found after reload, skipping timer setup.'; \
                 fi; \
               fi"
  else
    ghostmirror -DPo -mul "$GHOSTMIRROR_MIRRORLIST" "$GHOSTMIRROR_MIRRORLIST" -s light -S state,outofdate,morerecent,speed
    echo "Checking for ghostmirror.timer..."
    if systemctl --user list-unit-files ghostmirror.timer >/dev/null 2>&1; then
      echo "Timer unit found, enabling and starting..."
      systemctl --user enable ghostmirror.timer
      systemctl --user start ghostmirror.timer
    else
      echo "Warning: ghostmirror.timer unit not found. Trying to reload systemd user daemon..."
      systemctl --user daemon-reload
      if systemctl --user list-unit-files ghostmirror.timer >/dev/null 2>&1; then
        echo "Timer unit found after reload, enabling and starting..."
        systemctl --user enable ghostmirror.timer
        systemctl --user start ghostmirror.timer
      else
        echo "Timer unit still not found after reload, skipping timer setup."
      fi
    fi
  fi

  sudo pacman -Syy
else
  echo "Skipping ghostmirror install and setup."
fi

# --- Update and Packages (safe since mirrors are valid) ---
echo "Updating system..."
sudo pacman -Syu --noconfirm

initial_packages=(
  python-ignis-git
  ignis
)
packages=(
  hyprland
  dart-sass
  xdg-desktop-portal-hyprland
  xdg-desktop-portal-wlr
  xorg-xwayland
  qt5-wayland
  qt6-wayland
  qt5ct
  qt6ct
  libva
  linux-headers
  pipewire
  pipewire-alsa
  pipewire-pulse
  pipewire-jack
  pavucontrol
  python-aiohttp
  python-aiofiles
  wireplumber
  nm-connection-editor
  polkit-gnome
  hyprlock
  socat
  pamixer
  grim-hyprland-git
  grimblast-git
  meson
  cmake
  cpio
  pkgconf
  git
  gcc
  kitty
  thunar
  thunar-archive-plugin
  file-roller
  xdg-user-dirs
  python-requests
  python-jinja
  python-materialyoucolor
  python-pillow
  playerctl
  gpu-screen-recorder
  networkmanager
  ttf-jetbrains-mono
  ttf-jetbrains-mono-nerd
  ttf-nerd-fonts-symbols
  papirus-icon-theme
  upower
  wl-clipboard
  gnome-bluetooth-3.0
  goignis
  ignis-gvc
  brave-bin
  warp-terminal
)

for initial_pkg in "${initial_packages[@]}"; do
  if ! pacman -Qi "$initial_pkg" >/dev/null 2>&1 && ! yay -Qi "$initial_pkg" >/dev/null 2>&1; then
    echo "Installing $initial_pkg..."
    install_pkg "$initial_pkg"
  else
    echo "$initial_pkg is already installed."
  fi
done

echo "Initializing Ignis in background (stdout suppressed)..."
ignis init > /dev/null 2>&1 &

for pkg in "${packages[@]}"; do
  if ! pacman -Qi "$pkg" >/dev/null 2>&1 && ! yay -Qi "$pkg" >/dev/null 2>&1; then
    echo "Installing $pkg..."
    install_pkg "$pkg"
  else
    echo "$pkg is already installed."
  fi
done

# Copy themes/configs only if directories exist
if [[ -d ".config" ]]; then
  mkdir -p ~/.config
  cp -R .config/* ~/.config/
else
  echo "Warning: .config directory not found in current location"
fi

if [[ -d "ignis" ]]; then
  cp -R ignis ~/.config/
else
  echo "Warning: ignis directory not found in current location"
fi

if [[ -d "Material" ]]; then
  mkdir -p ~/.local/share/themes
  cp -R Material ~/.local/share/themes/
else
  echo "Warning: Material directory not found in current location"
fi

# Initialize ignis only if Hyprland session is active
if [[ "$XDG_CURRENT_DESKTOP" == "Hyprland" || -n "$(pgrep -x Hyprland)" ]]; then
  echo "Hyprland session detected, initializing Ignis..."
  ignis init > /dev/null 2>&1 &
else
  echo "Not in a Hyprland session, skipping Ignis initialization."
fi

# Enable and start NetworkManager if not running
if ! systemctl is-active --quiet NetworkManager; then
  sudo systemctl enable --now NetworkManager
fi

# Enable sddm display manager (don't start it immediately)
if ! systemctl is-enabled --quiet sddm; then
  sudo systemctl enable sddm
fi

# --- Hyprpm autorun setup (misc option) ---
if [[ "$perform_misc" == "y" || "$perform_misc" == "yes" ]]; then
  echo "Setting up Hyprland plugin autorun..."
  HYPR_CONFIG_DIR="$HOME/.config/hypr"
  HYPR_CONFIG="$HYPR_CONFIG_DIR/hyprland.conf"
  AUTOSTART_SCRIPT="$HYPR_CONFIG_DIR/hyprpm-setup.sh"
  mkdir -p "$HYPR_CONFIG_DIR"
  cat > "$AUTOSTART_SCRIPT" <<'EOF'
#!/bin/bash
SETUP_FLAG="$HOME/.config/hypr/.hyprpm-setup-done"
if [[ -f "$SETUP_FLAG" ]]; then
  exit 0
fi
sleep 3
if [[ -z "$HYPRLAND_INSTANCE_SIGNATURE" ]]; then
  echo "[Hyprpm Setup] Not in Hyprland session, exiting"
  exit 1
fi
kitty --hold -e bash -c '
  echo "=== Hyprland Plugin Setup ==="
  echo "Setting up hyprpm and plugins..."
  run_command() {
    local cmd="$1"
    local description="$2"
    echo "Running: $description"
    if eval "$cmd" 2>&1; then
      echo "✓ $description completed successfully"
      return 0
    else
      echo "✗ $description failed"
      return 1
    fi
  }
  echo "Updating plugin repositories..."
  run_command "hyprpm update" "Repository update"
  echo "Adding hyprland-plugins repository..."
  if ! hyprpm list repos | grep -q "hyprland-plugins"; then
    run_command "hyprpm add https://github.com/hyprwm/hyprland-plugins" "Adding repository"
  else
    echo "✓ Repository already exists"
  fi
  echo "Enabling hyprbars plugin..."
  run_command "hyprpm enable hyprbars" "Enabling hyprbars"
  echo "Building plugins..."
  BUILD_OUTPUT=$(hyprpm build 2>&1)
  BUILD_EXIT_CODE=$?
  echo "$BUILD_OUTPUT"
  if [[ $BUILD_EXIT_CODE -eq 0 ]] || echo "$BUILD_OUTPUT" | grep -qi -E "(built successfully|build completed|success|finished building)"; then
    echo "✓ Plugins built successfully"
    echo "Reloading Hyprland configuration..."
    if hyprctl reload 2>&1; then
      echo "✓ Configuration reloaded successfully"
      echo "🎉 Setup complete!"
    else
      echo "⚠ Configuration reload failed, but plugins should still work"
    fi
  else
    echo "✗ Plugin build may have failed"
    echo "Check the output above for details"
  fi
  echo ""
  echo "This setup will not run again."
  echo "Press Enter to close this window..."
  read -r
' && touch "$SETUP_FLAG"
EOF
  chmod +x "$AUTOSTART_SCRIPT"
  if [[ -f "$HYPR_CONFIG" ]]; then
    if ! grep -q "hyprpm-setup.sh" "$HYPR_CONFIG"; then
      echo "" >> "$HYPR_CONFIG"
      echo "# Auto-setup hyprpm plugins (runs once)" >> "$HYPR_CONFIG"
      echo "exec-once = $AUTOSTART_SCRIPT" >> "$HYPR_CONFIG"
      echo "Added autostart entry to hyprland.conf"
    else
      echo "Autostart entry already exists in hyprland.conf"
    fi
  else
    cat > "$HYPR_CONFIG" <<EOF
# Hyprland configuration
# Auto-setup hyprpm plugins (runs once)
exec-once = $AUTOSTART_SCRIPT
EOF
    echo "Created hyprland.conf with autostart entry"
  fi
  echo "Plugin autostart setup complete."
  echo "The setup will run automatically on first Hyprland login."
else
  echo "Skipping miscellaneous Hyprland plugin setup."
fi

echo "Preparation complete. You can now reboot and select the Hyprland session."
