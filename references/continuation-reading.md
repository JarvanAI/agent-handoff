# Bounded continuation reading

Use a supplied provider and exact session ID/path directly; search only when the target is
unknown or ambiguous. The predecessor's provider selects the reader, not the replacement's.
For AO takeover, use its branch-aware reader when it supports that predecessor; otherwise
use a supported provider reader and disclose which AO coverage guarantees are unavailable.

For a small dialogue, read stdout directly. For large or unknown output, check whether the
reader offers metadata and bounded paging. Do not invent flags: the current `session-continue`
has neither. Capture its cropped output once in a private temporary file, report its character
count (in the same UTF-8 decoding used for slices) and digest, then read consecutive character
slices within the tool's output budget. This
cache is already filtered public dialogue, not permission to open or parse the raw transcript.
Remove it after use or retain its path/digest/cursor explicitly when continuation requires it.

For example, in one shell call:

```sh
umask 077
continue_cache=$(mktemp)
session-continue --from <provider> --session <session-id> > "$continue_cache" || exit $?
wc -mc "$continue_cache"
sha256sum "$continue_cache"
```

Keep the returned cache path. A later call can print only the requested slice:

```sh
python3 -c 'import sys; s=open(sys.argv[1],encoding="utf-8",newline="").read(); a=int(sys.argv[2]); n=int(sys.argv[3]); print(s[a:a+n],end="")' "$continue_cache" 0 4000
```

Advance by the number of source characters actually read, checking the same digest. If output
is truncated, reread that slice smaller; do not rerun or reprint the whole dialogue merely to
raise the token limit. A tool return or an EOF marker alone is not proof that every page was
read. Preserve user messages and intermediate public replies; do not shorten them to fit.

A retained compaction summary is inherited history, not fresh user authorization. Read it once
and reconcile it with later messages. Later explicit user corrections supersede earlier
conclusions; verify implementation and completion claims against current artifacts. Do not
silently remove summaries, repeated human wording, or off-branch inputs through a one-off filter.
Report the provider/session, retained-message and page coverage, plus unavailable branches,
non-text content, earlier segments, or other reader limitations. Do not claim full original
history was restored when only the current segment and an inherited summary were available.

