$Host.UI.RawUI.WindowTitle = "Deploying Django Project"

# Configuration
$remoteHost = "202.169.231.66"
$remotePort = "1024"
$remoteUser = "surya"
$remotePassword = "surya123"
$localPath = "."
$remotePath = "/home/surya/django_project"

# Create a temporary script for scp
$scpScript = @"
spawn scp -P $remotePort -r $localPath/* $remoteUser@${remoteHost}:$remotePath
expect {
    "(yes/no)?" { send "yes\r"; exp_continue }
    "password:" { send "$remotePassword\r" }
}
expect eof
"@

# Save the script
$scpScript | Out-File -Encoding ASCII "deploy_script.exp"

# Use expect to run the scp command
Write-Host "Deploying project to $remoteHost..."
& expect -f deploy_script.exp

# Clean up
Remove-Item "deploy_script.exp"

Write-Host "Deployment complete!"
