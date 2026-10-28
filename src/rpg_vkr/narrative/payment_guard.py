"""Check explicit payment claims against engine-funded offers/receipts in new campaigns."""

import re
from decimal import Decimal

NUMBERS = {
    "ноль": 0,
    "один": 1,
    "одна": 1,
    "одну": 1,
    "одного": 1,
    "два": 2,
    "две": 2,
    "двух": 2,
    "три": 3,
    "трёх": 3,
    "четыре": 4,
    "четырёх": 4,
    "пять": 5,
    "пяти": 5,
    "шесть": 6,
    "шести": 6,
    "семь": 7,
    "семи": 7,
    "восемь": 8,
    "восьми": 8,
    "девять": 9,
    "девяти": 9,
    "десять": 10,
    "десяти": 10,
    "двадцать": 20,
    "тридцать": 30,
    "сорок": 40,
    "пятьдесят": 50,
    "шестьдесят": 60,
    "семьдесят": 70,
    "восемьдесят": 80,
    "девяносто": 90,
    "сто": 100,
    "двести": 200,
    "триста": 300,
    "четыреста": 400,
    "пятьсот": 500,
    "тысяча": 1000,
    "тысячу": 1000,
}
PATTERN = re.compile(
    r"(?<!\w)(\d+(?:[.,]\d+)?|(?:"
    + "|".join(sorted(NUMBERS, key=len, reverse=True))
    + r")(?:\s+(?:"
    + "|".join(sorted(NUMBERS, key=len, reverse=True))
    + r")){0,3})\s+(медн\w*|серебр\w*|золот\w*)",
    re.I,
)
PAYMENT = re.compile(
    r"обещ\w*|плат[ауыёе]|заплач\w*|заплат\w*|доплат\w*|вознагражден\w*|цен[ауы]|стоит|аванс\w*|получите|награда",
    re.I,
)


def validate(text, context):
    if not context or context.get("mechanics_revision") != 3:
        return
    allowed = {0}
    for q in context.get("contracts", []):
        allowed.add(q["reward_cp"])

    def collect(value):
        if isinstance(value, dict):
            for k, v in value.items():
                if k in ("reward_cp", "price_cp", "total_price_cp") and type(v) is int:
                    allowed.add(v)
                elif isinstance(v, (dict, list)):
                    collect(v)
        elif isinstance(value, list):
            for v in value:
                collect(v)

    collect(context.get("last_committed_receipt") or {})
    collect(context.get("receipt") or {})
    for sentence in re.split(r"(?<!\d)[.,;](?!\d)|[!?\n]", text):
        if re.search(
            r"не\s+(?:обещ\w*|предлага\w*|заплачу|заплатит\w*|получите|могу\s+заплатить|буду\s+платить)|не\s+(?:установлен\w*|подтверждён\w*|подтвержден\w*)",
            sentence,
            re.I,
        ):
            continue
        if re.search(
            r"(?:треть\w*|половин\w*|\d+\s*процент\w*)\s+(?:част\w*\s+ваш\w*|добыч\w*|прибыли|вам)",
            sentence,
            re.I,
        ):
            raise ValueError("Доля добычи не установлена договором движка.")
        if not PAYMENT.search(sentence):
            continue
        for match in PATTERN.finditer(sentence):
            spelling, unit = match.groups()
            if spelling[0].isdigit():
                number = Decimal(spelling.replace(",", "."))
            else:
                number = Decimal(sum(NUMBERS[w.casefold()] for w in spelling.split()))
            cp = number * (
                100
                if unit.casefold().startswith("золот")
                else 10
                if unit.casefold().startswith("серебр")
                else 1
            )
            if cp not in allowed:
                raise ValueError("Условия оплаты не подтверждены поручением или квитанцией движка.")
