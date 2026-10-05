import logging
import uuid
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.agent import Agent
from app.models.tool import Tool
from app.schemas.tool import (
    ResponseExtract,
    ToolCreate,
    ToolHeader,
    ToolParam,
    ToolResponse,
    ToolTestRequest,
    ToolTestResult,
    ToolUpdate,
)
from app.security import CurrentUser
from app.services import tool_executor
from app.services.crypto import SecretsKeyNotConfigured, decrypt_secrets, encrypt_secrets

logger = logging.getLogger("BOL.tools")

router = APIRouter(prefix="/tools", tags=["tools"])

# Capped below a tool's own configurable max (30s) so a misconfigured tool
# can't hang a dashboard request indefinitely.
_TEST_TIMEOUT_SEC = 15.0


def _to_response(tool: Tool) -> ToolResponse:
    secret_refs_set = sorted(decrypt_secrets(tool.secrets_enc).keys())
    return ToolResponse(
        id=tool.id,
        org_id=tool.org_id,
        name=tool.name,
        description=tool.description,
        is_active=tool.is_active,
        url=tool.url,
        method=tool.method,
        params=tool.params,
        headers=tool.headers,
        timeout_sec=tool.timeout_sec,
        retry_on_failure=tool.retry_on_failure,
        blocking=tool.blocking,
        pre_tool_speech=tool.pre_tool_speech,
        response_extract=tool.response_extract,
        secret_refs_set=secret_refs_set,
        created_at=tool.created_at,
        updated_at=tool.updated_at,
    )


def _validate_secret_refs(headers: list[ToolHeader], available_refs: set[str]) -> None:
    needed = {h.secret_ref for h in headers if h.value_type == "secret" and h.secret_ref}
    missing = needed - available_refs
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"headers reference secrets with no value provided: {sorted(missing)}",
        )


async def _get_org_tool(tool_id: uuid.UUID, org_id: uuid.UUID, db: AsyncSession) -> Tool:
    result = await db.execute(select(Tool).where(Tool.id == tool_id, Tool.org_id == org_id))
    tool = result.scalar_one_or_none()
    if tool is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")
    return tool


@router.get("", response_model=list[ToolResponse])
async def list_tools(
    current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[ToolResponse]:
    result = await db.execute(
        select(Tool).where(Tool.org_id == current_user.org_id).order_by(Tool.created_at.desc())
    )
    return [_to_response(tool) for tool in result.scalars().all()]


@router.get("/{tool_id}", response_model=ToolResponse)
async def get_tool(
    tool_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ToolResponse:
    return _to_response(await _get_org_tool(tool_id, current_user.org_id, db))


@router.post("", response_model=ToolResponse, status_code=status.HTTP_201_CREATED)
async def create_tool(
    payload: ToolCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ToolResponse:
    secret_values = {s.secret_ref: s.value for s in payload.secrets}
    _validate_secret_refs(payload.headers, set(secret_values))

    secrets_enc = None
    if secret_values:
        try:
            secrets_enc = encrypt_secrets(secret_values)
        except SecretsKeyNotConfigured as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    tool = Tool(
        org_id=current_user.org_id,
        name=payload.name,
        description=payload.description,
        is_active=payload.is_active,
        url=payload.url,
        method=payload.method,
        params=[p.model_dump() for p in payload.params],
        headers=[h.model_dump() for h in payload.headers],
        secrets_enc=secrets_enc,
        timeout_sec=payload.timeout_sec,
        retry_on_failure=payload.retry_on_failure,
        blocking=payload.blocking,
        pre_tool_speech=payload.pre_tool_speech.model_dump(),
        response_extract=[r.model_dump() for r in payload.response_extract],
    )
    db.add(tool)
    try:
        await db.commit()
    except Exception as exc:  # unique (org_id, name) violation
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"a tool named {payload.name!r} already exists",
        ) from exc
    await db.refresh(tool)
    return _to_response(tool)


@router.patch("/{tool_id}", response_model=ToolResponse)
async def update_tool(
    tool_id: uuid.UUID,
    payload: ToolUpdate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ToolResponse:
    tool = await _get_org_tool(tool_id, current_user.org_id, db)
    data = payload.model_dump(exclude_unset=True, exclude={"secrets"})

    if "params" in data:
        tool.params = data["params"]
    if "headers" in data:
        tool.headers = data["headers"]
    if "pre_tool_speech" in data:
        tool.pre_tool_speech = data["pre_tool_speech"]
    if "response_extract" in data:
        tool.response_extract = data["response_extract"]
    for field_name in (
        "name",
        "description",
        "is_active",
        "url",
        "method",
        "timeout_sec",
        "retry_on_failure",
        "blocking",
    ):
        if field_name in data:
            setattr(tool, field_name, data[field_name])

    # Validate secret_refs against the headers as they'll stand after this
    # update (payload.headers if replaced, else the tool's existing ones).
    headers_after = (
        payload.headers if payload.headers is not None else [ToolHeader(**h) for h in tool.headers]
    )

    if payload.secrets is not None:
        available = decrypt_secrets(tool.secrets_enc)
        for item in payload.secrets:
            available[item.secret_ref] = item.value
        _validate_secret_refs(headers_after, set(available))
        if available:
            try:
                tool.secrets_enc = encrypt_secrets(available)
            except SecretsKeyNotConfigured as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
        else:
            tool.secrets_enc = None
    else:
        _validate_secret_refs(headers_after, set(decrypt_secrets(tool.secrets_enc)))

    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"a tool named {data.get('name', tool.name)!r} already exists",
        ) from exc
    await db.refresh(tool)
    return _to_response(tool)


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(
    tool_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    tool = await _get_org_tool(tool_id, current_user.org_id, db)

    result = await db.execute(select(Agent).where(Agent.org_id == current_user.org_id))
    referencing = [
        agent.name
        for agent in result.scalars().all()
        for entry in agent.tools
        if entry.get("type") == "tool_ref" and entry.get("tool_id") == str(tool_id)
    ]
    if referencing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"tool is still used by agent(s): {', '.join(referencing)}",
        )

    await db.delete(tool)
    await db.commit()


@router.post("/{tool_id}/test", response_model=ToolTestResult)
async def test_tool(
    tool_id: uuid.UUID,
    payload: ToolTestRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ToolTestResult:
    """Runs the real HTTP request (through the same executor and SSRF guard
    a live call uses) with caller-supplied values for this tool's LLM params
    and placeholder dynamic vars, so a misconfigured header or URL is caught
    before a real caller hits it."""
    tool = await _get_org_tool(tool_id, current_user.org_id, db)

    params = [ToolParam(**p) for p in tool.params]
    headers_cfg = [ToolHeader(**h) for h in tool.headers]
    response_extract = [ResponseExtract(**r) for r in tool.response_extract]
    secrets = decrypt_secrets(tool.secrets_enc)

    dynamic_ctx = tool_executor.build_dynamic_context(
        call_id="test-call",
        agent_id="test-agent",
        org_id=str(current_user.org_id),
        caller_number="+15555550100",
        to_number="+15555550101",
        direction="test",
        transport="test",
    )

    try:
        url, query, body, header_values = tool_executor.resolve_params(
            tool.url, params, payload.llm_args, dynamic_ctx
        )
    except tool_executor.ToolParamError as exc:
        return ToolTestResult(ok=False, duration_ms=0, request_url=tool.url, error=str(exc))

    for h in headers_cfg:
        header_values[h.name] = (
            secrets.get(h.secret_ref, "") if h.value_type == "secret" else h.value
        )

    async with httpx.AsyncClient() as client:
        result = await tool_executor.run_tool(
            url=url,
            method=tool.method,
            query=query,
            body=body,
            headers=header_values,
            timeout_sec=min(tool.timeout_sec, _TEST_TIMEOUT_SEC),
            retry_on_failure=False,
            response_extract=response_extract,
            client=client,
        )

    return ToolTestResult(
        ok=result.ok,
        status_code=result.status_code,
        duration_ms=result.duration_ms,
        request_headers=result.request_header_names,
        request_url=result.request_url,
        response_body=result.response_body,
        extracted=result.extracted,
        error=result.error,
    )
