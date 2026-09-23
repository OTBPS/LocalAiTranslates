; Client edition installer.
;
; Nothing is duplicated here on purpose: defining ClientEdition switches the
; identity block in installer.common.iss, and the whole installer script is
; then shared with the full edition. Any fix to installation, upgrade,
; downgrade protection or uninstall therefore applies to both.
#define ClientEdition
#include "installer.iss"
