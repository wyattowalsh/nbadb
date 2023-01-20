<div align='center'>
    <h1><code>basketball_db</code></h1>
    <h4><a href="stats.nba.com">stats.nba.com</a> Data Extraction in <i><u>Python3</u></i></h4>
    <img src="./utils/img/logo-wide-bg.svg"/>
</div>

---

## Installation and Usage

### Install Brew

```zsh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

note: ensure to follow along within the console output as several commands that are printed will need to be executed.

### Run Setup Script and Activate Virtual Environment

```zsh
brew install --cask miniconda
```

```zsh
chmod u+x ./utils/setup.sh && chmod 744 ./utils/setup.sh && ./utils/setup.sh
```

```zsh
conda activate basketball_db
```

---

## Included Endpoints

[nba_api](https://github.com/swar/nba_api) is utilized to extract data from [stats.nba.com](https://stats.nba.com). See a list of all available endpoints [here](https://github.com/swar/nba_api/tree/master/docs/nba_api/stats/endpoints).

Currently, the following endpoints are included in the database:

- [Players](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/static/players.md)
- [Teams](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/static/teams.md)
- [LeagueGameLog](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/leaguegamelog.md)
- [CommonPlayerInfo](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/commonplayerinfo.md)
- [TeamDetails](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/teamdetails.md)
- [BoxScoreSummaryV2](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/boxscoresummaryv2.md)
- [PlayByPlayV2](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/playbyplayv2.md)
