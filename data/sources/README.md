# `data/sources/`

Raw conference inputs (committed snapshots).


| File             | Description                                                                                                                                                                                   |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `programme.json` | Talk schedule, presenters, affiliations scraped from the [online site](https://innovators-icrs2026programme.eventsairsite.com/) via EventsAir's API                                           |
| `abstracts.json` | Talk abstracts                                                                                                                                                                                |
| `delegates.json` | Parsed delegate list from provided [PDF](https://airdrive.eventsair.com/eventsairaueprod/production-innovators-public/20d10b81d8cd43ad9b0fc3a08e5695f4) (Created Thu July 09 2026 3:39:45 AM) |


Loaded by `src/sources/programme.py` and `src/sources/delegates.py`.

The app is built using publicly-available data: the [most recent official delegate list](https://airdrive.eventsair.com/eventsairaueprod/production-innovators-public/20d10b81d8cd43ad9b0fc3a08e5695f4), the [online programme](https://innovators-icrs2026programme.eventsairsite.com/) (titles, abstracts, author lists), and in some cases, delegates' public webpages and emails.