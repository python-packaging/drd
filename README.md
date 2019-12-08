# DRD (Deletions Record Daemon)

Seeing as warehouse does not yet have a feed of packages removed, this lets us
keep track of when deletions are recorded using publicly-accessible metadata.

Updates are very quick, and occur in a repo such that you can `git commit -a; git
push` afterward.

This is live at http://drd.nonstandards.org/simple/ as a PEP 503 mirror
(additionally with the default json as well).

# Cache storage

The on-disk format is shared with [honesty](https://pypi.org/project/honesty/)
with some additions.  We do not do traditional cache fetches with etag, instead
relying on the serials.  If you need to do an initial fetch, use
`scripts/refresh.py --force` the first time (before `~/.cache/honesty/serials`
has any files).

# How to run

Make sure that `~/.cache/honesty` is preserved between runs, and run

```
scripts/refresh.py
```

from the git checkout.  You can then `git commit -a -m ...; git push` if you
want to update the git repo.

I plan to make it possible to annotate deletions as to whether they were
malicious or not, but this is future work.
