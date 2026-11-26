$Deck = "deck@steamdeck.local"
$Plugin = "/home/deck/homebrew/plugins/frame-view"
$Stage = "/tmp/frame-view"

# Build the plugin
npm run build

# Clear the staging folder
ssh $Deck "rm -rf $Stage && mkdir -p $Stage"

# Copy the plugin files
scp -r dist main.py plugin.json package.json py_modules "${Deck}:$Stage/"

# Move the plugin files to the Decky folder then reload (as root)
ssh -t $Deck "sudo sh -c 'rm -rf $Plugin && cp -r $Stage $Plugin && chmod -R u=rwX,go=rX $Plugin && systemctl restart plugin_loader'"