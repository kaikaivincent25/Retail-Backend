from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.user import UserRole


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shop_id: int
    full_name: str
    username: str
    role: UserRole
    is_active: bool


Username = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=50)]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]


class UserCreate(BaseModel):
    username: Username
    full_name: FullName
    role: UserRole
    password: str = Field(..., min_length=6, max_length=100)


class UserUpdate(BaseModel):
    full_name: FullName | None = None
    role: UserRole | None = None
    is_active: bool | None = None

class ProfileUpdate(BaseModel):
    full_name: FullName | None = None
    username: Username | None = None


class PasswordChange(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=100)