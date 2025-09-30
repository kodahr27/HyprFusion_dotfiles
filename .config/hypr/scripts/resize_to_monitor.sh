#!/bin/sh
LOGFILE=/tmp/hypr_resize.log
echo "Script started at $(date)" >> "$LOGFILE"

within_tolerance() {
  a=$1
  b=$2
  tol=$3
  diff=$((a > b ? a - b : b - a))
  [ "$diff" -le "$tol" ]
}

win_id=$(hyprctl activewindow -j | jq -r '.address')
STATEFILE="/tmp/hypr_resize_state_${win_id}.json"

res=$(hyprctl monitors active | grep -oP '\d+x\d+@' | head -n1 | tr -d '@')
width=$(printf '%s' "$res" | cut -d'x' -f1)
height=$(printf '%s' "$res" | cut -d'x' -f2)

reserved_height=86
offset=1
new_height=$((height - reserved_height))
adjusted_movement=$((reserved_height / 2 + offset))

echo "Detected resolution: $width x $height" >> "$LOGFILE"
echo "Reserved height for bars: $reserved_height" >> "$LOGFILE"

if [ -n "$width" ] && [ -n "$new_height" ] && [ "$new_height" -gt 0 ]; then

    if [ -f "$STATEFILE" ]; then
        original=$(cat "$STATEFILE")

        target_width=$(printf '%s\n' "$original" | jq -r '.target.width')
        target_height=$(printf '%s\n' "$original" | jq -r '.target.height')
        target_x=$(printf '%s\n' "$original" | jq -r '.target.x')
        target_y=$(printf '%s\n' "$original" | jq -r '.target.y')

        current=$(hyprctl activewindow -j)
        curr_x=$(printf '%s' "$current" | jq -r '.at[0]')
        curr_y=$(printf '%s' "$current" | jq -r '.at[1]')
        curr_width=$(printf '%s' "$current" | jq -r '.size[0]')
        curr_height=$(printf '%s' "$current" | jq -r '.size[1]')

        echo "Current geometry : width=$curr_width, height=$curr_height, x=$curr_x, y=$curr_y" >> "$LOGFILE"
        echo "Saved target geometry: width=$target_width, height=$target_height, x=$target_x, y=$target_y" >> "$LOGFILE"

        tolerance=43

        if within_tolerance "$curr_width" "$target_width" "$tolerance" && \
           within_tolerance "$curr_height" "$target_height" "$tolerance" && \
           within_tolerance "$curr_x" "$target_x" "$tolerance" && \
           within_tolerance "$curr_y" "$target_y" "$tolerance" ; then

            echo "Restoring original size and position for window $win_id" >> "$LOGFILE"
            orig_width=$(printf '%s\n' "$original" | jq -r '.original.width')
            orig_height=$(printf '%s\n' "$original" | jq -r '.original.height')
            orig_x=$(printf '%s\n' "$original" | jq -r '.original.x')
            orig_y=$(printf '%s\n' "$original" | jq -r '.original.y')

            # Adjust Y coordinate by subtracting adjusted_movement offset to compensate
            adjusted_orig_y=$((orig_y - reserved_height - offset))

            /usr/bin/hyprctl dispatch resizeactive exact "$orig_width" "$orig_height" >> "$LOGFILE" 2>&1
            /usr/bin/hyprctl dispatch moveactive "$orig_x" "$adjusted_orig_y" >> "$LOGFILE" 2>&1

            rm -f "$STATEFILE"
            echo "Window restored and state reset" >> "$LOGFILE"
            exit 0
        else
            echo "Window geometry changed beyond tolerance; deleting state and continuing normally" >> "$LOGFILE"
            rm -f "$STATEFILE"
        fi
    fi

    echo "Saving current and target window state for window $win_id" >> "$LOGFILE"
    current=$(hyprctl activewindow -j)

    curr_x=$(printf '%s' "$current" | jq -r '.at[0]')
    curr_y=$(printf '%s' "$current" | jq -r '.at[1]')
    curr_width=$(printf '%s' "$current" | jq -r '.size[0]')
    curr_height=$(printf '%s' "$current" | jq -r '.size[1]')

    echo "Saving original: width=$curr_width, height=$curr_height, x=$curr_x, y=$curr_y" >> "$LOGFILE"
    echo "Saving target: width=$width, height=$new_height, x=0, y=$adjusted_movement" >> "$LOGFILE"

    jq -n --arg ow "$curr_width" --arg oh "$curr_height" --arg ox "$curr_x" --arg oy "$curr_y" \
          --arg tw "$width" --arg th "$new_height" --arg tx "0" --arg ty "$adjusted_movement" \
          '{original: {width: ($ow | tonumber), height: ($oh | tonumber), x: ($ox | tonumber), y: ($oy | tonumber)}, target: {width: ($tw | tonumber), height: ($th | tonumber), x: ($tx | tonumber), y: ($ty | tonumber)}}' > "$STATEFILE"

    /usr/bin/hyprctl dispatch setfloating 1 >> "$LOGFILE" 2>&1
    /usr/bin/hyprctl dispatch resizeactive exact "$width" "$new_height" >> "$LOGFILE" 2>&1
    /usr/bin/hyprctl dispatch centerwindow >> "$LOGFILE" 2>&1
    /usr/bin/hyprctl dispatch moveactive 0 "$adjusted_movement" >> "$LOGFILE" 2>&1

    echo "Window resized, centered, and moved with offset" >> "$LOGFILE"
else
    echo "Failed to compute correct resolution" >> "$LOGFILE"
fi
