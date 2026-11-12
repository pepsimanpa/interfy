from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from ..database import get_db
from ..models import User, UserRole
from ..account_lifecycle import active_users_query, find_replacement_admin, permanently_delete_user
from ..schemas import Token, UserCreate, UserRead, UserRoleUpdate
from ..auth import hash_password, verify_password, create_access_token, get_current_user, require_admin

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing and not existing.is_deleted:
        raise HTTPException(status_code=409, detail="이미 사용 중인 아이디입니다.")

    try:
        if existing:
            # A legacy soft-deleted row might still occupy the original login ID.
            # Remove it fully while preserving its project and audit references.
            replacement_admin = find_replacement_admin(db)
            if replacement_admin is None:
                raise HTTPException(status_code=409, detail="기존 삭제 계정을 정리할 관리자가 없습니다.")
            permanently_delete_user(existing, db, replacement_admin)

        user = User(
            email=payload.email,
            display_name=payload.email,
            password_hash=hash_password(payload.password),
            role=UserRole.USER,
        )
        db.add(user)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="이미 사용 중인 아이디입니다.") from exc

    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = active_users_query(db).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    return Token(access_token=create_access_token(str(user.id)))


@router.get("/users", response_model=list[UserRead])
def list_users(db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    return active_users_query(db).order_by(User.created_at.desc(), User.id.desc()).all()


@router.delete("/users/me")
def withdraw_me(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.email == "admin":
        raise HTTPException(status_code=400, detail="기본 관리자 계정은 탈퇴할 수 없습니다.")

    replacement_admin = find_replacement_admin(db, excluding_user_id=current_user.id)
    if current_user.role == UserRole.ADMIN and replacement_admin is None:
        raise HTTPException(status_code=400, detail="마지막 관리자 계정은 탈퇴할 수 없습니다. 다른 관리자 계정을 먼저 생성하거나 권한을 부여하세요.")

    if replacement_admin is None:
        replacement_admin = find_replacement_admin(db)

    if replacement_admin is None:
        raise HTTPException(status_code=400, detail="계정 삭제를 처리할 관리자 계정이 없습니다.")
    permanently_delete_user(current_user, db, replacement_admin)
    db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    user = active_users_query(db).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="현재 로그인된 계정은 여기서 삭제할 수 없습니다. 계정 화면의 회원탈퇴를 이용하세요.")
    if user.email == "admin":
        raise HTTPException(status_code=400, detail="기본 관리자 계정은 삭제할 수 없습니다.")

    permanently_delete_user(user, db, current_user)
    db.commit()
    return {"ok": True}


@router.patch("/users/{user_id}/role", response_model=UserRead)
def update_user_role(user_id: int, payload: UserRoleUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    user = active_users_query(db).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="현재 로그인된 계정의 권한은 변경할 수 없습니다.")
    user.role = payload.role
    db.commit()
    db.refresh(user)
    return user


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)):
    return current_user
