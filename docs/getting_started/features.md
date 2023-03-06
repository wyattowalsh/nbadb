(features)=

# Project Features

- Custom [**Python3**](https://docs.python.org/3/) package for the efficient extraction and compilation of [**_nba_api_**](https://github.com/swar/nba_api) data.
  - [`pandera`](https://pandera.readthedocs.io/) for data schema definition and validation.
- [**_Poetry_**](https://python-poetry.org/) for Python packaging and dependency management.
- [**_Sphinx_**](https://www.sphinx-doc.org/en/master/) Python package documentation site.

  - [**_PyData Theme_**](https://pydata-sphinx-theme.readthedocs.io/en/stable/)
  - _Open Sans font_ [via Google Fonts](https://fonts.google.com/specimen/Open+Sans)
  - **Sphinx Extensions** include:

    - [`sphinx.ext.autodoc`](https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html) -- Include documentation from docstrings
    - [`sphinx.ext.autosectionlabel`](https://www.sphinx-doc.org/en/master/usage/extensions/autosectionlabel.html) -- Allow reference sections using its title
    - [`sphinx.ext.autosummary`](https://www.sphinx-doc.org/en/master/usage/extensions/autosummary.html) -- Generate autodoc summaries
    - [`sphinx.ext.graphviz`](https://www.sphinx-doc.org/en/master/usage/extensions/graphviz.html) -- Add Graphviz graphs
    - [`sphinx.ext.napoleon`](https://www.sphinx-doc.org/en/master/usage/extensions/napoleon.html) -- Support for NumPy and Google style docstrings
    - [`sphinx.ext.todo`](https://www.sphinx-doc.org/en/master/usage/extensions/todo.html) -- Support for todo items
    - [`sphinx.ext.viewcode`](https://www.sphinx-doc.org/en/master/usage/extensions/viewcode.html) -- Add links to highlighted source code
    - [`sphinx_git`](https://sphinx-git.readthedocs.io/en/latest/)
      - > sphinx-git is an extension to the Sphinx documentation tool that allows you to include excerpts from your git history within your documentation. This could be used for release changelogs, to pick out specific examples of history in documentation, or just to surface what is happening in the project.
    - [`sphinx_markdown_builder`](https://github.com/clayrisser/sphinx-markdown-builder) -- sphinx builder that outputs markdown files.
    - [`sphinx_copybutton`](https://sphinx-copybutton.readthedocs.io/en/latest/) -- add a little “copy” button to the right of your code blocks.
    - [`sphinx_design`](https://sphinx-design.readthedocs.io/en/furo-theme/) -- A sphinx extension for designing beautiful, screen-size responsive web-components.
    - [`myst_parser`](https://myst-parser.readthedocs.io/en/latest/) -- A Sphinx and Docutils extension to parse MyST, a rich and extensible flavour of Markdown for authoring technical and scientific documentation.
      - Extensions include:
        - [`amsmath`](https://myst-parser.readthedocs.io/en/latest/syntax/optional.html)
        - [`dollarmath`](https://myst-parser.readthedocs.io/en/latest/syntax/optional.html)
        - [`smartquotes`](https://myst-parser.readthedocs.io/en/latest/syntax/optional.html)
        - [`strikethrough`](https://myst-parser.readthedocs.io/en/latest/syntax/optional.html)
        - [`colon_fence`](https://myst-parser.readthedocs.io/en/latest/syntax/optional.html)
        - [`deflist`](https://myst-parser.readthedocs.io/en/latest/syntax/optional.html)
        - [`tasklist`](https://myst-parser.readthedocs.io/en/latest/syntax/optional.html)
        - [`attrs_inline`](https://myst-parser.readthedocs.io/en/latest/syntax/optional.html)
        - [`html_image`](https://myst-parser.readthedocs.io/en/latest/syntax/optional.html)
        - [`html_admonition`](https://myst-parser.readthedocs.io/en/latest/syntax/optional.html)
    - [`sphinxcontrib.mermaid`](https://sphinxcontrib-mermaid-demo.readthedocs.io/en/latest/) -- embed Mermaid graphs in your documents, including general flowcharts, sequence and gantt diagrams.
    - [`sphinx-hoverxref`](https://sphinx-hoverxref.readthedocs.io/en/latest/) -- show a floating window (tooltips or modal dialogues) on the cross references of the documentation embedding the content of the linked section on them. With sphinx-hoverxref, you don’t need to click a link to see what’s in there.
    - [`sphinx-sitemap`](https://sphinx-sitemap.readthedocs.io/en/latest/index.html) -- A Sphinx extension to generate multi-version and multi-language sitemaps.org compliant sitemaps for the HTML version of your Sphinx documentation.
    - [`sphinx_togglebutton`](https://sphinx-togglebutton.readthedocs.io/en/latest/) -- A small sphinx extension to add “toggle button” elements to sections of your page. For example:

      - ```{toggle}
        This is a toggle button
        ```

    - [`sphinx_favicon`](https://sphinx-favicon.readthedocs.io/en/latest) -- A Sphinx extension to add custom favicons. With Sphinx Favicon, you can add custom favicons to your Sphinx HTML documentation.

- [`isort`](https://pycqa.github.io/isort/) -- a Python utility / library to sort imports alphabetically, and automatically separated into sections and by type. It provides a command line utility, Python library and plugins for various editors to quickly sort all your imports.
- [`Black`](https://black.readthedocs.io/en/stable/) -- uncompromising code formatter.
- [`Pylint`](https://pylint.readthedocs.io/en/latest/) -- is a static code analyser for Python 2 or 3. The latest version supports Python 3.7.2 and above. Pylint analyses your code without actually running it. It checks for errors, enforces a coding standard, looks for code smells, and can make suggestions about how the code could be refactored.
- [`autoflake`](https://github.com/PyCQA/autoflake) -- Removes unused imports and unused variables as reported by pyflakes.
- [`pylama`](https://github.com/klen/pylama) -- Code audit tool for python.
- [`hypothesis`](https://hypothesis.readthedocs.io/en/latest/) -- Python library for creating unit tests which are simpler to write and more powerful when run, finding edge cases in your code you wouldn’t have thought to look for. It is stable, powerful and easy to add to any existing test suite.
- [`pytest`](https://docs.pytest.org/) -- The pytest framework makes it easy to write small, readable tests, and can scale to support complex functional testing for applications and libraries.
  - Extensions include:
    - [`pytest-sugar`](https://github.com/Teemu/pytest-sugar) -- This plugin extends pytest by showing failures and errors instantly, adding a progress bar, improving the test results, and making the output look better.
    - [`pytest-emoji`](https://github.com/hackebrot/pytest-emoji) -- A pytest plugin that adds emojis to your test result report 😍
    - [`pytest-html`](https://pytest-html.readthedocs.io/en/latest/) -- plugin for pytest that generates a HTML report for test results.
    - [`pytest-icdiff`](https://github.com/hjwp/pytest-icdiff) -- better error messages for assert equals in pytest.
    - [`pytest-instafail`](https://github.com/pytest-dev/pytest-instafail) -- py.test plugin to show failures instantly.
    - [`pytest-timeout`](https://github.com/pytest-dev/pytest-timeout) -- This plugin will time each test and terminate it when it takes too long. Termination may or may not be graceful, please see below, but when aborting it will show a stack dump of all thread running at the time. This is useful when running tests under a continuous integration server or simply if you don't know why the test suite hangs.
    - [`pytest-benchmark`](https://pytest-benchmark.readthedocs.io/) -- py.test fixture for benchmarking code.
    - [`pytest-cov`](https://pytest-cov.readthedocs.io/) -- Coverage plugin for pytest.
    - [`pytest-xdist`](https://pytest-xdist.readthedocs.io/) -- extends pytest with new test execution modes, the most used being distributing tests across multiple CPUs to speed up test execution.
- [`tabulate`](https://github.com/astanin/python-tabulate) -- Pretty-print tabular data in Python, a library and a command-line utility.
