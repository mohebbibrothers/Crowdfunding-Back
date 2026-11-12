"""موتور درخت مرکل دودویی (RFC 6962 Domain-Separated Binary Merkle Tree) برای شفافیت رمزنگاری‌شده.

ویژگی‌های امنیتی:
- تفکیک دامنهٔ برگ (پیشوند ``0x00``) و گره میانی (پیشوند ``0x01``) برای مصونیت ریاضی کامل در برابر
  حملات Second-Preimage.
- عدم ذخیره یا افشای هیچ‌گونه دادهٔ هویتی خیر (شماره موبایل یا نام) در هش برگ‌ها؛ تنها یک تعهد
  نمک‌زدهٔ یک‌طرفه (``commitment_nonce``) همراه با شناسهٔ مشارکت، تعداد سهم و مبلغ ریالی هش می‌شود.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from typing import Any

LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"


@dataclass(frozen=True, slots=True)
class MerkleLeafInput:
    """ورودی استاندارد یک برگ مشارکت قطعی در درخت شفافیت حرکت."""

    contribution_id: str
    receipt_verification_code: str
    shares_count: int
    matched_shares: int
    amount_rial: int


def compute_leaf_hash(item: MerkleLeafInput, *, secret_salt: str) -> str:
    """محاسبهٔ هش برگ مرکل با پیشوند ``0x00`` و تعهد نمک‌زده بدون نشت اطلاعات هویتی."""
    blinded_tag = hmac.new(
        secret_salt.encode("utf-8"),
        f"{item.contribution_id}:{item.receipt_verification_code}".encode(),
        hashlib.sha256,
    ).hexdigest()[:32]
    canonical = (
        f"crowdfunding.merkle.v1|{item.contribution_id}|{blinded_tag}|"
        f"{item.shares_count}|{item.matched_shares}|{item.amount_rial}"
    ).encode()
    return hashlib.sha256(LEAF_PREFIX + canonical).hexdigest()


def hash_internal_pair(left_hex: str, right_hex: str) -> str:
    """ترکیب دو گره فرزند با پیشوند ``0x01`` برای تشکیل گره والد."""
    payload = NODE_PREFIX + bytes.fromhex(left_hex) + bytes.fromhex(right_hex)
    return hashlib.sha256(payload).hexdigest()


def build_merkle_levels(leaf_hashes: list[str]) -> list[list[str]]:
    """ساخت تمام سطوح درخت مرکل از برگ‌ها تا ریشه (سطح آخر شامل تک‌عنصر ``merkle_root`` است)."""
    if not leaf_hashes:
        empty_root = hashlib.sha256(LEAF_PREFIX + b"crowdfunding.merkle.v1|EMPTY").hexdigest()
        return [[empty_root]]

    levels: list[list[str]] = [list(leaf_hashes)]
    current = list(leaf_hashes)
    while len(current) > 1:
        next_level: list[str] = []
        for idx in range(0, len(current), 2):
            left = current[idx]
            right = current[idx + 1] if idx + 1 < len(current) else current[idx]
            next_level.append(hash_internal_pair(left, right))
        levels.append(next_level)
        current = next_level
    return levels


def generate_inclusion_proof(
    leaf_hashes: list[str], target_index: int
) -> tuple[str, list[dict[str, str]]]:
    """تولید ریشهٔ مرکل و مسیر اثبات شمول (Inclusion Proof) برای برگ در اندیس ``target_index``."""
    if not leaf_hashes or target_index < 0 or target_index >= len(leaf_hashes):
        raise ValueError("اندیس برگ در درخت مرکل نامعتبر است.")

    levels = build_merkle_levels(leaf_hashes)
    proof: list[dict[str, str]] = []
    idx = target_index

    for level in levels[:-1]:
        if idx % 2 == 0:
            sibling_idx = idx + 1 if idx + 1 < len(level) else idx
            proof.append({"position": "right", "hash": level[sibling_idx]})
        else:
            sibling_idx = idx - 1
            proof.append({"position": "left", "hash": level[sibling_idx]})
        idx //= 2

    root_hash = levels[-1][0]
    return root_hash, proof


def verify_inclusion_proof(
    *,
    leaf_hash: str,
    proof: list[dict[str, Any]],
    expected_root: str,
) -> bool:
    """راستی‌آزمایی ریاضی مستقل اثبات شمول یک برگ در ریشهٔ مرکل منتشرشده."""
    try:
        bytes.fromhex(leaf_hash)
        bytes.fromhex(expected_root)
    except ValueError:
        return False

    current = leaf_hash.lower()
    for step in proof:
        pos = str(step.get("position", ""))
        sibling = str(step.get("hash", "")).lower()
        try:
            bytes.fromhex(sibling)
        except ValueError:
            return False
        if pos == "right":
            current = hash_internal_pair(current, sibling)
        elif pos == "left":
            current = hash_internal_pair(sibling, current)
        else:
            return False
    return hmac.compare_digest(current, expected_root.lower())
