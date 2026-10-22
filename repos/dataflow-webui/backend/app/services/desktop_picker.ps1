param([switch]$DirectoriesOnly)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Windows.Forms
function Show-OwnedDialog($Dialog) {
    # A background worker has no foreground window. Give the native dialog a
    # topmost owner so it cannot disappear behind the browser after the menu closes.
    $owner = New-Object System.Windows.Forms.Form
    $owner.ShowInTaskbar = $false
    $owner.StartPosition = 'CenterScreen'
    $owner.Size = New-Object System.Drawing.Size(1, 1)
    $owner.Opacity = 0
    $owner.TopMost = $true
    try {
        $owner.Show()
        $owner.Activate()
        return $Dialog.ShowDialog($owner)
    } finally { $owner.Dispose() }
}
$paths = @()
$folder = $DirectoriesOnly.IsPresent
if (-not $DirectoriesOnly) {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Import local sources"
    $form.Width = 340
    $form.Height = 140
    $form.StartPosition = "CenterScreen"
    $form.TopMost = $true
    $files = New-Object System.Windows.Forms.Button
    $files.Text = "Choose files"
    $files.SetBounds(20, 25, 130, 35)
    $files.DialogResult = [System.Windows.Forms.DialogResult]::Yes
    $folders = New-Object System.Windows.Forms.Button
    $folders.Text = "Choose folder"
    $folders.SetBounds(170, 25, 130, 35)
    $folders.DialogResult = [System.Windows.Forms.DialogResult]::No
    $form.Controls.AddRange(@($files, $folders))
    try { $choice = $form.ShowDialog() } finally { $form.Dispose() }
    if ($choice -eq [System.Windows.Forms.DialogResult]::Cancel) { Write-Output '[]'; exit 0 }
    $folder = $choice -eq [System.Windows.Forms.DialogResult]::No
}
if ($folder) {
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = "Choose a local folder"
    try {
        if ((Show-OwnedDialog $dialog) -eq [System.Windows.Forms.DialogResult]::OK) { $paths = @($dialog.SelectedPath) }
    } finally { $dialog.Dispose() }
} else {
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = "Choose local source files"
    $dialog.Multiselect = $true
    try {
        if ((Show-OwnedDialog $dialog) -eq [System.Windows.Forms.DialogResult]::OK) { $paths = @($dialog.FileNames) }
    } finally { $dialog.Dispose() }
}
ConvertTo-Json -InputObject @($paths) -Compress
