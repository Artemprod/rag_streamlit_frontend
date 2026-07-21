import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder


def show_table(df: pd.DataFrame, key: str) -> None:
    builder = GridOptionsBuilder.from_dataframe(df)
    builder.configure_default_column(resizable=True, filterable=True, sortable=True)
    builder.configure_pagination(paginationPageSize=50)
    AgGrid(
        df,
        gridOptions=builder.build(),
        height=600,
        fit_columns_on_grid_load=True,
        key=key,
    )