#!/bin/bash
declare -A windows_applied  # Tracks windows already processed (by address)

# Cascade variables
cascade_offset=30
cascade_x=300
cascade_y=100
max_cascade=10  # Reset after 10 windows
cascade_count=0 # Counter for placed windows

# Function to apply cascade rules to a window
apply_cascade_to_window() {
  local addr="$1"
  
  # Get window info
  win=$(hyprctl clients -j | jq -c --arg a "$addr" '.[] | select(.address==$a)')
  
  if [[ -z "$win" ]]; then
    echo "Window $addr not found"
    return
  fi
  
  local class=$(echo "$win" | jq -r '.class')
  local title=$(echo "$win" | jq -r '.title')
  local width=$(echo "$win" | jq -r '.size[0]')
  local height=$(echo "$win" | jq -r '.size[1]')

  # Skip very small windows (likely popups/tooltips)
  if [[ $width -lt 200 || $height -lt 200 ]]; then
    echo "Ignoring small window $addr (${width}x${height}) - likely popup/tooltip"
    return
  fi

  # Skip windows with empty titles (often popups)
  if [[ -z "$title" || "$title" == "null" ]]; then
    echo "Ignoring window $addr with empty title - likely popup"
    return
  fi

  # If window not already processed
  if [ -z "${windows_applied[$addr]}" ]; then
    echo "Applying cascade rules to window $addr (title: '$title') at position ${cascade_x},${cascade_y}"
    
    # Apply cascade positioning
    hyprctl dispatch movewindowpixel "exact $cascade_x $cascade_y,address:$addr"
    hyprctl dispatch resizewindowpixel "exact 1000 700,address:$addr"
    
    # Update cascade position for next window
    cascade_x=$((cascade_x + cascade_offset))
    cascade_y=$((cascade_y + cascade_offset))
    cascade_count=$((cascade_count + 1))
    
    # Reset cascade if we've reached the max
    if [[ $cascade_count -ge $max_cascade ]]; then
      cascade_x=300
      cascade_y=100
      cascade_count=0
      echo "Resetting cascade position after $max_cascade windows"
    fi
    
    # Mark this window as processed
    windows_applied[$addr]=1
  fi
}

# Function to handle window close events
handle_window_close() {
  local addr="$1"
  if [[ -n "${windows_applied[$addr]}" ]]; then
    unset "windows_applied[$addr]"
    echo "Window $addr closed, removed from ignore list."
  fi
}

echo "Starting Hyprland window manager with socket events..."

# Listen to Hyprland socket events
socat -U - UNIX-CONNECT:"$XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE/.socket2.sock" | while read -r line; do
  event=$(echo "$line" | cut -d'>' -f1)
  data=$(echo "$line" | cut -d'>' -f3-)  # Skip the empty field between >>
  
  case "$event" in
    "openwindow")
      # Format: openwindow>>ADDRESS,WORKSPACENAME,WINDOWCLASS,WINDOWTITLE
      addr="0x$(echo "$data" | cut -d',' -f1)"
      echo "New window opened: $addr"
      apply_cascade_to_window "$addr"
      ;;
    "closewindow")
      # Format: closewindow>>ADDRESS
      addr="0x$data"
      handle_window_close "$addr"
      ;;
  esac
done
