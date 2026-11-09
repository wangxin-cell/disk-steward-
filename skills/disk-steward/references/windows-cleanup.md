# Windows cleanup and leftovers

Start with Settings → System → Storage and its cleanup recommendations/temporary file categories, or the application's own storage manager. UI labels vary by Windows version. The user must choose applicable categories; Downloads, Recycle Bin and previous Windows installations can contain wanted files or recovery options.

Use Microsoft-supported servicing for the component store. Never manually remove files from `C:\Windows\WinSxS`, `C:\Windows\Installer`, `System Volume Information`, Windows Update stores, or protected application directories. Do not disable hibernation, restore points or pagefiles merely to improve a score; those change system capabilities and require a specific informed decision.

For an uninstalled application: establish the product and actual install status; separate user documents, shared data, caches and configuration; prefer the official removal/repair procedure. Preserve unknown content and shared runtimes. “No matching uninstall entry” is not enough evidence of a leftover. Registry sweeping is not part of this skill.

Use the optional [application-registration evidence](application-evidence.md) workflow to correlate supported installation-location records with already-scanned candidates. It reads registration metadata and adds associations to the decision report. It does not discover every application, establish that a product was uninstalled, or authorize cleanup of an unmatched directory.

For app caches, consult the app's current documentation and use its own maintenance command or UI. Describe the cost of rebuilding and any network requirement. Do not recurse-delete `%TEMP%`, AppData or Downloads as a category. Locked files should be skipped, not unlocked by killing unrelated processes. Do not take ownership of protected paths.

Before an approved manual cleanup, resolve every exact absolute target and confirm it stays inside the user-approved directory; reject drive roots and links/junctions. Use a single shell and literal paths throughout. The alpha intentionally supplies no general recursive deletion helper.

References (consult for version-specific procedures):

- [Microsoft: Free up drive space in Windows](https://support.microsoft.com/en-us/windows/free-up-drive-space-in-windows-85529ccb-c365-490d-b548-831022bc9b32)
- [Microsoft: Clean up the WinSxS folder](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/clean-up-the-winsxs-folder?view=windows-11)

Cleanup that can erase user files or recovery history needs an approved concrete scope. Do not treat navigating to the Storage settings page as deletion approval.
