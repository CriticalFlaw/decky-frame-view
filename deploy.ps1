# Clear the staging folder
ssh deck@steamdeck.local "rm -rf /tmp/frame-view && mkdir -p /tmp/frame-view"

# Copy the plugin files
scp -r dist main.py plugin.json package.json py_modules deck@steamdeck.local:/tmp/frame-view/

# Move the plugin files to the Decky folder then reload
ssh -t deck@steamdeck.local "sudo rm -rf /home/deck/homebrew/plugins/frame-view && sudo cp -r /tmp/frame-view /home/deck/homebrew/plugins/frame-view && sudo systemctl restart plugin_loader"