from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Query, Session


ModelType = TypeVar("ModelType")
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class CrudBase(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    model: type[ModelType] | None = None
    deleted_field = "deleted"
    deleted_no = "N"
    deleted_yes = "Y"

    def __init__(self, db: Session, model: type[ModelType] | None = None):
        self.db = db
        self.model = model or self.model

        if self.model is None:
            raise ValueError("CrudBase requires a SQLAlchemy model.")

    def get(self, id: Any, *, include_deleted: bool = False) -> ModelType | None:
        db_obj = self.db.get(self.model, id)

        if db_obj is None:
            return None

        if not include_deleted and self._is_deleted(db_obj):
            return None

        return db_obj

    def get_multi(
        self,
        skip: int = 0,
        limit: int = 100,
        *,
        include_deleted: bool = False,
    ) -> list[ModelType]:
        query = self._query(include_deleted=include_deleted)
        return query.offset(skip).limit(limit).all()

    def create(
        self,
        obj_in: CreateSchemaType | dict[str, Any],
        *,
        commit: bool = True,
        refresh: bool = True,
    ) -> ModelType:
        obj_data = self._to_dict(obj_in)
        self._set_default_deleted(obj_data)
        db_obj = self.model(**obj_data)

        self.db.add(db_obj)

        if commit:
            self.db.commit()

            if refresh:
                self.db.refresh(db_obj)
        else:
            self.db.flush()

        return db_obj

    def update(
        self,
        db_obj: ModelType,
        obj_in: UpdateSchemaType | dict[str, Any],
        *,
        commit: bool = True,
        refresh: bool = True,
    ) -> ModelType:
        obj_data = self._to_dict(obj_in, exclude_unset=True)

        for field, value in obj_data.items():
            setattr(db_obj, field, value)

        self.db.add(db_obj)

        if commit:
            self.db.commit()

            if refresh:
                self.db.refresh(db_obj)
        else:
            self.db.flush()

        return db_obj

    def delete(
        self,
        id: Any,
        *,
        commit: bool = True,
    ) -> ModelType | None:
        db_obj = self.get(id)

        if db_obj is None:
            return None

        if self._has_deleted_field():
            setattr(db_obj, self.deleted_field, self.deleted_yes)
            self.db.add(db_obj)
        else:
            self.db.delete(db_obj)

        if commit:
            self.db.commit()
        else:
            self.db.flush()

        return db_obj

    def restore(
        self,
        id: Any,
        *,
        commit: bool = True,
        refresh: bool = True,
    ) -> ModelType | None:
        db_obj = self.get(id, include_deleted=True)

        if db_obj is None:
            return None

        if not self._has_deleted_field():
            return db_obj

        setattr(db_obj, self.deleted_field, self.deleted_no)
        self.db.add(db_obj)

        if commit:
            self.db.commit()

            if refresh:
                self.db.refresh(db_obj)
        else:
            self.db.flush()

        return db_obj

    def hard_delete(
        self,
        id: Any,
        *,
        commit: bool = True,
    ) -> ModelType | None:
        db_obj = self.get(id, include_deleted=True)

        if db_obj is None:
            return None

        self.db.delete(db_obj)

        if commit:
            self.db.commit()
        else:
            self.db.flush()

        return db_obj

    def _to_dict(
        self,
        obj: BaseModel | dict[str, Any],
        *,
        exclude_unset: bool = False,
    ) -> dict[str, Any]:
        if isinstance(obj, BaseModel):
            return obj.model_dump(exclude_unset=exclude_unset)

        return dict(obj)

    def _query(self, *, include_deleted: bool = False) -> Query:
        query = self.db.query(self.model)

        if include_deleted or not self._has_deleted_field():
            return query

        deleted_column = getattr(self.model, self.deleted_field)
        return query.filter(deleted_column == self.deleted_no)

    def _has_deleted_field(self) -> bool:
        return hasattr(self.model, self.deleted_field)

    def _is_deleted(self, db_obj: ModelType) -> bool:
        if not self._has_deleted_field():
            return False

        return getattr(db_obj, self.deleted_field) == self.deleted_yes

    def _set_default_deleted(self, obj_data: dict[str, Any]) -> None:
        if self._has_deleted_field() and self.deleted_field not in obj_data:
            obj_data[self.deleted_field] = self.deleted_no
