// Telling Explorer that the icon changed.
//
// Included into a [Code] section, so the comments here are Pascal ones.
// A leading `;` is a comment in the script sections but not in this one,
// where it parses as an empty statement and the compiler then chokes on
// the prose after it.
//
// Windows caches application icons aggressively. Replacing the
// executable and the ICO in place is not enough: the taskbar, Explorer
// and existing shortcuts keep drawing the old artwork until something
// invalidates the cache, which otherwise means a sign-out.
//
// SHCNE_ASSOCCHANGED is the documented way to say "icons may have
// moved"; it is cheap and does nothing when nothing changed. Shared by
// the full, client and incremental scripts so the declaration cannot
// drift between them.

procedure SHChangeNotify(EventId: Integer; Flags: Cardinal; Item1, Item2: Cardinal);
  external 'SHChangeNotify@shell32.dll stdcall';

procedure RefreshShellIcons();
begin
  // SHCNE_ASSOCCHANGED, SHCNF_IDLIST
  SHChangeNotify($08000000, $0000, 0, 0);
end;
