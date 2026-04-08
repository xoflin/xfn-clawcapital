"""
Skill: notifications/telegram
Envia teses de investimento via Telegram e aguarda aprovação humana.

Fluxo:
  1. Gestor gera briefing + decisão → chama request_approval()
  2. Este módulo envia mensagem formatada ao utilizador
  3. Aguarda /sim ou /não (ou timeout) via long-polling
  4. Devolve ApprovalResult ao orquestrador
  5. Orquestrador só executa se approved=True

Dependências:
  pip install python-telegram-bot>=21.0

Variáveis de ambiente:
  TELEGRAM_BOT_TOKEN  — token do bot (obtido via @BotFather)
  TELEGRAM_CHAT_ID    — chat ID do utilizador (obtido via @userinfobot ou primeira mensagem)

Timeout por defeito: 300 segundos (5 minutos).
Se o utilizador não responder dentro do timeout → aprovação rejeitada automaticamente.
"""

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes


# ------------------------------------------------------------------
# Tipos de retorno
# ------------------------------------------------------------------

@dataclass
class ApprovalResult:
    approved: bool
    decision: Literal["sim", "não", "timeout", "erro"]
    responded_at: str | None = None
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "approved":     self.approved,
            "decision":     self.decision,
            "responded_at": self.responded_at,
            "reason":       self.reason,
        }


# ------------------------------------------------------------------
# Formatação da mensagem
# ------------------------------------------------------------------

def _format_thesis(briefing: dict) -> str:
    """
    Converte o briefing do agente gestor numa mensagem Telegram legível.

    O briefing deve conter:
      ticker, direction, combined_score, confidence,
      price, stop_loss_price, position_size_usd, risk_usd,
      thesis (str — resumo da tese do gestor)
      macro_context (str — opcional)
      technical_summary (str — opcional)
      sentiment_summary (str — opcional)
    """
    ticker      = briefing.get("ticker", "?")
    direction   = briefing.get("direction", "?")
    score       = briefing.get("combined_score", 0)
    confidence  = briefing.get("confidence", 0)
    price       = briefing.get("price", 0)
    stop_price  = briefing.get("stop_loss_price", 0)
    size_usd    = briefing.get("position_size_usd", 0)
    risk_usd    = briefing.get("risk_usd", 0)
    thesis      = briefing.get("thesis", "Sem tese disponível.")
    macro       = briefing.get("macro_context", "")
    technical   = briefing.get("technical_summary", "")
    sentiment   = briefing.get("sentiment_summary", "")

    direction_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(direction, "❓")
    conf_pct = f"{confidence * 100:.0f}%"

    lines = [
        f"*ClawCapital — Tese de Investimento*",
        f"",
        f"{direction_emoji} *{ticker}* — {direction}",
        f"Score: `{score:+.3f}` | Confiança: `{conf_pct}`",
        f"",
        f"💰 *Posição*",
        f"  Entrada: `${price:,.4f}`",
        f"  Stop Loss: `${stop_price:,.4f}`",
        f"  Tamanho: `${size_usd:,.2f}`",
        f"  Risco máximo: `${risk_usd:,.2f}`",
        f"",
        f"📋 *Tese*",
        f"{thesis}",
    ]

    if macro:
        lines += ["", f"🏦 *Macro*", macro]
    if technical:
        lines += ["", f"📈 *Técnico*", technical]
    if sentiment:
        lines += ["", f"📰 *Sentimento*", sentiment]

    lines += [
        "",
        "─" * 30,
        "Responde com /sim para aprovar ou /não para rejeitar.",
        f"_(timeout em 5 min)_",
    ]

    return "\n".join(lines)


# ------------------------------------------------------------------
# Aprovação assíncrona (interno)
# ------------------------------------------------------------------

async def _send_and_await(
    bot_token: str,
    chat_id: str | int,
    message: str,
    timeout_seconds: int,
) -> ApprovalResult:
    """
    Envia a mensagem e aguarda resposta via long-polling.
    Devolve ApprovalResult quando o utilizador responde ou o timeout expira.
    """
    result_holder: list[ApprovalResult] = []
    answered = asyncio.Event()

    async def handle_sim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if str(update.effective_chat.id) != str(chat_id):
            return
        result_holder.append(ApprovalResult(
            approved=True,
            decision="sim",
            responded_at=datetime.now(timezone.utc).isoformat(),
        ))
        await update.message.reply_text("✅ Aprovado. A executar ordem...")
        answered.set()

    async def handle_nao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if str(update.effective_chat.id) != str(chat_id):
            return
        result_holder.append(ApprovalResult(
            approved=False,
            decision="não",
            responded_at=datetime.now(timezone.utc).isoformat(),
        ))
        await update.message.reply_text("❌ Rejeitado. Ordem cancelada.")
        answered.set()

    app = (
        Application.builder()
        .token(bot_token)
        .build()
    )
    app.add_handler(CommandHandler("sim", handle_sim))
    app.add_handler(CommandHandler("nao", handle_nao))   # /nao sem acento (Telegram limita comandos a ASCII)
    app.add_handler(CommandHandler("não", handle_nao))   # fallback por se o cliente suportar

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    # Enviar a tese
    try:
        await app.bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError as e:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        return ApprovalResult(
            approved=False,
            decision="erro",
            reason=f"Falha ao enviar mensagem: {e}",
        )

    # Aguardar resposta ou timeout
    try:
        await asyncio.wait_for(answered.wait(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        result_holder.append(ApprovalResult(
            approved=False,
            decision="timeout",
            reason=f"Sem resposta em {timeout_seconds}s — ordem cancelada por segurança.",
        ))
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text="⏱ Timeout — ordem cancelada automaticamente.",
            )
        except TelegramError:
            pass

    await app.updater.stop()
    await app.stop()
    await app.shutdown()

    return result_holder[0] if result_holder else ApprovalResult(
        approved=False,
        decision="erro",
        reason="Estado interno inválido.",
    )


# ------------------------------------------------------------------
# API pública
# ------------------------------------------------------------------

def request_approval(
    briefing: dict,
    bot_token: str | None = None,
    chat_id: str | int | None = None,
    timeout_seconds: int = 300,
) -> ApprovalResult:
    """
    Envia uma tese de investimento via Telegram e aguarda aprovação humana.

    Args:
        briefing:        Dict com os dados da tese (ver _format_thesis).
        bot_token:       Token do bot Telegram. Usa TELEGRAM_BOT_TOKEN se None.
        chat_id:         Chat ID do utilizador. Usa TELEGRAM_CHAT_ID se None.
        timeout_seconds: Segundos a aguardar antes de rejeitar automaticamente.

    Returns:
        ApprovalResult com approved=True/False e detalhes da decisão.

    Raises:
        ValueError: Se bot_token ou chat_id não estiverem disponíveis.
    """
    token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
    cid   = chat_id  or os.environ.get("TELEGRAM_CHAT_ID")

    if not token:
        raise ValueError(
            "bot_token não fornecido e TELEGRAM_BOT_TOKEN não está definido."
        )
    if not cid:
        raise ValueError(
            "chat_id não fornecido e TELEGRAM_CHAT_ID não está definido."
        )

    message = _format_thesis(briefing)

    return asyncio.run(
        _send_and_await(
            bot_token=token,
            chat_id=cid,
            message=message,
            timeout_seconds=timeout_seconds,
        )
    )


def send_notification(
    text: str,
    bot_token: str | None = None,
    chat_id: str | int | None = None,
) -> bool:
    """
    Envia uma mensagem simples (sem aguardar resposta).
    Útil para alertas, confirmações de execução, erros críticos.

    Returns:
        True se enviado com sucesso, False caso contrário.
    """
    token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
    cid   = chat_id  or os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not cid:
        return False

    async def _send() -> bool:
        bot = Bot(token=token)
        try:
            await bot.send_message(chat_id=cid, text=text, parse_mode=ParseMode.MARKDOWN)
            return True
        except TelegramError:
            return False

    return asyncio.run(_send())
