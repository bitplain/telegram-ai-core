"""Registry skills."""

from __future__ import annotations

import logging

from app.skills.schemas import SkillProfile

log = logging.getLogger(__name__)


CHAT_SKILL = SkillProfile(
    id="chat",
    name="Универсальный чат",
    description="Дефолтный режим: общий ассистент на сбалансированной модели.",
    agent_id="general",
    model_id="default_balanced",
    temperature=0.7,
    trigger_commands=["/chat"],
    trigger_keywords=[],
    enabled=True,
)

FAST_SKILL = SkillProfile(
    id="fast",
    name="Быстрые ответы",
    description="Короткие быстрые ответы на дешёвой модели.",
    agent_id="general",
    model_id="default_fast",
    temperature=0.5,
    trigger_commands=["/fast"],
    trigger_keywords=["быстро", "коротко", "fast"],
    enabled=True,
)

ASK_SKILL = SkillProfile(
    id="ask",
    name="Одноразовый вопрос агенту",
    description="Внутренний навык для /ask без смены активного режима.",
    agent_id="general",
    model_id="default_balanced",
    temperature=0.4,
    trigger_commands=["/ask"],
    trigger_keywords=[],
    enabled=True,
)

PORTFOLIO_SKILL = SkillProfile(
    id="portfolio",
    name="Портфель ETH",
    description="Показать сохранённый в боте баланс ETH и оценку в USD.",
    agent_id="crypto",
    model_id="crypto_model",
    temperature=0.2,
    trigger_commands=["/portfolio", "/balance"],
    trigger_keywords=["портфель", "баланс eth", "сколько eth"],
    enabled=True,
)

CRYPTO_SKILL = SkillProfile(
    id="crypto",
    name="Криптоанализ",
    description="Анализ криптовалют, токенов, протоколов и on-chain метрик.",
    agent_id="crypto",
    model_id="crypto_model",
    temperature=0.4,
    trigger_commands=["/crypto"],
    trigger_keywords=[
        "рынок",
        "рынке",
        "крипторынок",
        "крипта",
        "крипто",
        "bitcoin",
        "btc",
        "eth",
        "ethereum",
        "solana",
        "sol",
        "defi",
        "nft",
        "blockchain",
        "блокчейн",
        "токен",
        "альткоин",
    ],
    enabled=True,
)

DEFI_SKILL = SkillProfile(
    id="defi",
    name="DeFi",
    description="Разбор DeFi-протоколов, доходностей, TVL и рисков.",
    agent_id="crypto",
    model_id="crypto_model",
    temperature=0.3,
    trigger_commands=["/defi"],
    trigger_keywords=["defi", "tvl", "apy", "yield", "ликвидность"],
    enabled=True,
)

TOKEN_SKILL = SkillProfile(
    id="token",
    name="Token analysis",
    description="Разбор токенов, токеномики и рыночных рисков.",
    agent_id="crypto",
    model_id="crypto_model",
    temperature=0.3,
    trigger_commands=["/token"],
    trigger_keywords=["tokenomics", "токеномика"],
    enabled=True,
)

FINANCE_SKILL = SkillProfile(
    id="finance",
    name="Финансовый анализ",
    description="Акции, индексы, макроэкономика и личные финансы.",
    agent_id="finance",
    model_id="finance_model",
    temperature=0.4,
    trigger_commands=["/finance"],
    trigger_keywords=[
        "акция",
        "акции",
        "stock",
        "stocks",
        "etf",
        "облигация",
        "облигации",
        "bond",
        "ставка",
        "процентная ставка",
        "ipo",
        "дивиденд",
        "инфляция",
        "макро",
    ],
    enabled=True,
)

NEWS_SKILL = SkillProfile(
    id="news",
    name="Новостная сводка",
    description="Краткие пересказы новостей и сводки по теме.",
    agent_id="news",
    model_id="news_model",
    temperature=0.3,
    trigger_commands=["/news"],
    trigger_keywords=["новости", "news", "сводка", "пересказ", "headline"],
    enabled=True,
)

SUMMARIZE_NEWS_SKILL = SkillProfile(
    id="summarize_news",
    name="Краткая новостная сводка",
    description="Сжатое изложение новостного текста или события.",
    agent_id="news",
    model_id="news_model",
    temperature=0.2,
    trigger_commands=["/summarize_news"],
    trigger_keywords=["кратко новости", "сводка новостей"],
    enabled=True,
)

DEVOPS_SKILL = SkillProfile(
    id="devops",
    name="DevOps / Infra",
    description="Linux, Docker, Kubernetes, CI/CD, облачная инфраструктура.",
    agent_id="devops",
    model_id="devops_model",
    temperature=0.2,
    trigger_commands=["/devops", "/infra"],
    trigger_keywords=[
        "docker",
        "kubernetes",
        "k8s",
        "linux",
        "bash",
        "ansible",
        "terraform",
        "ci/cd",
        "github actions",
        "gitlab ci",
        "nginx",
        "systemd",
        "helm",
        "prometheus",
        "grafana",
    ],
    enabled=True,
)


ALL_SKILLS: list[SkillProfile] = [
    CHAT_SKILL,
    ASK_SKILL,
    FAST_SKILL,
    PORTFOLIO_SKILL,
    CRYPTO_SKILL,
    DEFI_SKILL,
    TOKEN_SKILL,
    FINANCE_SKILL,
    NEWS_SKILL,
    SUMMARIZE_NEWS_SKILL,
    DEVOPS_SKILL,
]


DEFAULT_SKILL_ID = CHAT_SKILL.id


class SkillRegistry:
    def __init__(self, profiles: list[SkillProfile] | None = None) -> None:
        items = profiles if profiles is not None else ALL_SKILLS
        self._items: dict[str, SkillProfile] = {p.id: p for p in items}
        self._default_id = DEFAULT_SKILL_ID

    def get(self, skill_id: str | None) -> SkillProfile:
        if skill_id and skill_id in self._items:
            return self._items[skill_id]
        if skill_id:
            log.warning(
                "Unknown skill_id '%s' — falling back to default '%s'",
                skill_id,
                self._default_id,
            )
        return self._items[self._default_id]

    def get_or_none(self, skill_id: str) -> SkillProfile | None:
        return self._items.get(skill_id)

    def list_enabled(self) -> list[SkillProfile]:
        return [p for p in self._items.values() if p.enabled]

    def list_all(self) -> list[SkillProfile]:
        return list(self._items.values())

    @property
    def default_id(self) -> str:
        return self._default_id


_registry = SkillRegistry()


def get_skill_registry() -> SkillRegistry:
    return _registry


__all__ = [
    "SkillRegistry",
    "get_skill_registry",
    "ALL_SKILLS",
    "DEFAULT_SKILL_ID",
]
