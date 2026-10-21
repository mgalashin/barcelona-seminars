# Barcelona Econ Seminars

One agenda of the economics seminars at UB, UPF, UAB, IESE and Esade, rebuilt every morning.

**Live page:** https://mgalashin.github.io/barcelona-seminars/

## Where the data comes from

| Source | Covers |
|---|---|
| [BSE events calendar](https://events.bse.eu/all) (JSON feed) | UPF Dept. of Economics and Business, CREI, UAB (UFAE, Bellaterra series, MicroLab), IAE-CSIC, BSE-wide lectures |
| [UB School of Economics activities](https://www.ub.edu/school-economics/activities/) | IEB, AQR-IREA, IPERG, Economic Theory, Game Theory, Economic History, thesis defences |
| [IESE Research Seminars](https://blog.iese.edu/financeseminars/seminars/) | IESE's economics and finance series |
| [Esade GREF events](https://www.esade.edu/faculty-research/en/group-research-economics-finance/events) | Esade's economics and finance research seminars |

## How it refreshes

`.github/workflows/update.yml` runs every day at 05:30 UTC (07:30 Barcelona time in summer, 06:30 in winter). It:

1. runs `collect.py`, which fetches all four sources and writes `data/seminars.json` and the site in `docs/`;
2. commits the new data back to the repo;
3. publishes `docs/` to GitHub Pages;
4. fails if any source could not be reached, so GitHub emails you.

If a source is down, or suddenly returns no events when it had some the day before (usually a site redesign that broke the parser), the page keeps that source's events from the last good run and flags the source as unreachable. The other sources still update.

To refresh by hand, open the **Actions** tab, choose **Refresh seminars**, and click **Run workflow**. Or run:

```sh
gh workflow run update.yml
```

GitHub turns off scheduled workflows in public repos after 60 days without repository activity. The daily data commits should keep it active. If the schedule ever stops, re-enable it in the Actions tab.

## Run it locally

Python 3.9 or newer, no extra packages.

```sh
python3 collect.py                # build for the current academic year
python3 collect.py --fail IESE    # test the fallback: treat IESE as down
open docs/index.html
```

The academic year runs 1 September to 31 July and switches over each August.

## Host it somewhere else

`docs/` is a plain static site. Any server works: run `python3 collect.py` from cron once a day and serve the `docs/` folder.

## Files

- `collect.py`: fetches, parses and normalises the four sources, then renders the page
- `page_template.html`: the page (HTML, CSS and JS); the data is injected at `__SEMINARS_DATA__`
- `data/seminars.json`: the latest data, also the fallback store for the next run
- `docs/`: the generated site (`index.html`, `seminars.json`)
