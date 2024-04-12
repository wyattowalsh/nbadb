"""
File       : nbadb/nbaDbHelper.py
Author     : @wyattowalsh
Description: nbadb CLI module.
"""
from rich import print
from typer import Typer

from nbadb.nbaDbHelper import NbaDbHelper

app = Typer()


@app.command()
def extract( write_to_db: bool = True ):
    """runs the database extraction

    Args:
        write_to_db (bool, optional): whether to write the data to the database. Defaults to True.
    """
    helper = NbaDbHelper()
    print( "Extracting data from NBA API..." )
    helper.getTeamDetails( write_to_db=write_to_db )


if __name__ == "__main__":
    app()
