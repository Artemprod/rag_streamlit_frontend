from pydantic import BaseModel


class Document(BaseModel):
    text: str
    description: str
    is_good: bool
    estimation: float
