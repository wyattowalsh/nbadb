---
notoc: true
---

```{raw} html
<h1 style="font-size: 1.65rem; font-weight: 900;"><b>Welcome to <a style="color: #20BEFF;" href="https://www.kaggle.com/datasets/wyattowalsh/basketball" target="_blank" rel="noopener noreferrer">The NBA Database</a> Code Base Docs Site</b> <span class="wave">👋</span>&nbsp;<span class="ball">🏀</span></h1>
```

```{image} ./_static/img/logo-wide-bg.svg
:align: center
:class: welcome-image
:alt: The NBA Database Cover Image
```

```{raw} html
<blockquote><p style="font-size: large; font-weight: 700;"><i>Here, you can find info on setup, usage, and development of the NBA Database code base</i></p></blockquote>
```

```{raw} html
<form class="bd-search align-items-center" action="search.html" method="get">
    <input type="search" class="form-control search-front-page" name="q" id="search-input" placeholder="&#128269; Search the NBA Database docs site..." aria-label="Search the NBA Database docs site..." autocomplete="on">
</form>
```

---

## About

This site contains all relevant information for the code base associated with the [**NBA Database** on **_Kaggle_**](https://www.kaggle.com/datasets/wyattowalsh/basketball).

The {ref}`nba_db` package contains the associated code base responsible for producing the [**NBA Database** on Kaggle](https://www.kaggle.com/datasets/wyattowalsh/basketball).

The package is written in [**Python3**](https://docs.python.org/3/) and can be utilized by scripting or in a [**Jupyter Environment**](https://jupyter.org/) (e.g. JupyterLab or Jupyter Notebook).

---

## Site Contents

````{grid} 1
:margin: 1
```{grid-item-card} <i class="fa-solid fa-flag-checkered"></i> Getting Started
:link: getting-started
:link-type: ref
:img-top: ./_static/img/map-location-dot-solid.svg
:padding: 2
:shadow: lg
:columns: 6
Visit here for information on installation, development environment initialization and configuration, and project usage notes.
```
```{grid-item-card} <i class="fa-solid fa-map-location-dot"></i> User Guide
:link: user-guide
:link-type: ref
:img-top: ./_static/img/book-bookmark-solid.svg
:padding: 2
:shadow: lg
:columns: 6
Catch up on relevant project documentation (e.g. data schemas, package usage, etc.).
```
```{grid-item-card} <i class="fa-solid fa-magnifying-glass-chart"></i> API Reference
:link: reference
:link-type: ref
:img-top: ./_static/img/code-solid.svg
:padding: 2
:shadow: lg
:columns: 6
View the API reference for a complete list of all modules and functions within the {package}`nba_db` package.
```
```{grid-item-card} <i class="fa-solid fa-oil-well"></i> Developer Guide
:link: development
:link-type: ref
:img-top: ./_static/img/people-group-solid.svg
:padding: 2
:shadow: lg
:columns: 6
See the developer guide for information on contributing to the project.
```
````

---

```{include} ./getting_started/features.md

```

---

## Indices and tables

- {ref}`genindex`
- {ref}`modindex`
- {ref}`search`

```{toctree}
:maxdepth: 1
:titlesonly:
:hidden:

getting_started/index
user_guide/index
reference/index
development/index
```

---

## Change Log

```{git_changelog}

```
