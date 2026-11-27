#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""importador_gct.py — Importador de referência para templates .gct (GCS).

Calibração do importador previsto na v0.7.2 do kit Singular. Regras R1–R24
conforme `Analise_formato_GCT.md` (§§12, 15–18): parsers tolerantes com
fallback honesto — reconheço → converto; não reconheço → guardo bruto + aviso.

USO
    python3 importador_gct.py <arquivo|diretorio|zip> [...] [--out DIR] [--selftest]

SAÍDAS (em --out, padrão ./out_importador)
    relatorio_importacao.md    – resumo pós-importação (R8)
    canonicos/<slug>.json      – JSON canônico por template (chaves estáveis)
    stdout                     – linha por arquivo + totais finais
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import zipfile
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constantes de domínio (fonte: guia oficial GCS + acervo do dono dos dados)
# ---------------------------------------------------------------------------
VERSION_MIN = 2          # MinimumDataVersion do GCS
VERSION_MAX_TESTED = 5   # CurrentDataVersion observado (janela analisada)

FAMILIAS = {
    "template_legacy": "Template GCS v1/v2 sem cabeçalho (nosso corpus)",
    "template_moderno": "Template GCS com Header (file_type/version)",
    "sheet_gcs": "Ficha completa (.gcs) — suportada (fase 2)",
    "character_export": "Export JSON tipo 'character' (.gcs.txt) — suportada (fase 2)",
    "externo_singular": "Formato do ecossistema Singular — candidata futura",
    "desconhecida": "Não identificada",
}

TIPOS_VANTAGEM_OK = {"advantage", "advantage_container"}
CONTAINER_TIPOS = {"race", "meta_trait"}

FEATURES_KNOWN = {
    "attribute_bonus", "dr_bonus", "skill_bonus", "reaction_bonus", "spell_bonus",
    "weapon_bonus", "cost_reduction", "dx", "iq",
    # tipos vistos em amostras adicionais:
    "conditional_modifier",
}
PREREQ_TIPOS_KNOWN = {"prereq_list", "advantage_prereq", "skill_prereq", "trait_prereq", "script_prereq"}

# Escopos de suporte (v0.7.2) — fase 1: templates .gct; fase 2: fichas completas
ESCOPO_FASE1 = "fase1-template"
ESCOPO_FASE2 = "fase2-ficha"
ESCOPO_FORA = "fora-do-escopo"
CONJ_FASE1 = {"template_legacy", "template_moderno"}
CONJ_FASE2 = {"sheet_gcs", "character_export"}
CONJ_FORA = {"externo_singular", "desconhecida"}
SUFIXOS_SUPORTADOS = (".gct", ".gcs", ".gcs.txt", ".json")

# Tabela §18 — tipos de dano e modos de golpe (PT ↔ EN)
DANO_PT = {"cut": "corte", "cr": "cont", "imp": "perf", "pi": "pa", "fat": "fad",
           "burn": "qmd", "corte": "corte", "cont": "cont", "perf": "perf", "pa": "pa", "fad": "fad", "qmd": "qmd"}
ST_PT = {"thr": "GdP", "sw": "GeB", "GdP": "GdP", "GeB": "GeB"}

PLACEHOLDER_RE = re.compile(r"@([A-Za-zÀ-ÖØ-öø-ÿ_][^@\n]{0,80})@")
NUM_RE = re.compile(r"^[-+]?\d+(?:\.\d+)?$")


# ---------------------------------------------------------------------------
# Helpers de normalização
# ---------------------------------------------------------------------------
def numero(v: Any) -> Optional[float]:
    """Coerção numérica defensiva (R6): número/número-em-string → float|int; resto → None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        s = v.strip()
        if NUM_RE.match(s):
            f = float(s)
            return int(f) if f.is_integer() else f
    return None


def num_str(v: Any) -> Any:
    """Como `numero`, mas devolve o texto cru quando não é número puro (para 'C,1', '3/dia', 'Não')."""
    n = numero(v)
    return n if n is not None else (v.strip() if isinstance(v, str) else v)


def lang_de(txt: str) -> str:
    """Heurística leve pt/en (R7): presença de caracteres latinos acentuados ⇒ pt."""
    if not isinstance(txt, str):
        return "?"
    if any(c in "àáâãäçèêëíïîóôõöùüûñÁÂÃÇÈÊËÍÎÓÔÕÚÛÑ" for c in txt):
        return "pt"
    return "en" if any(c.isalpha() for c in txt) else "?"


def slug(name: str) -> str:
    """Nome de arquivo seguro, preservando acentos."""
    s = re.sub(r'[<>:/\\|?*\x00-\x1f]', "-", name).strip().replace(" ", "_")
    return s[:120] or "sem_nome"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Avisos:
    """Coletores de avisos por arquivo (níveis: info/warn/erro)."""

    def __init__(self) -> None:
        self.lista: List[Dict[str, str]] = []

    def add(self, nivel: str, codigo: str, msg: str) -> None:
        self.lista.append({"nivel": nivel, "codigo": codigo, "msg": msg})

    def contagem(self) -> Counter:
        return Counter(a["codigo"] for a in self.lista)

    def __len__(self) -> int:
        return len(self.lista)


# ---------------------------------------------------------------------------
# Leitura e identificação de envelope (R13/R15)
# ---------------------------------------------------------------------------
def ler_arquivo(path: Path) -> Tuple[Any, bytes, Optional[str]]:
    raw = path.read_bytes()
    err = None
    try:
        txt = raw.decode("utf-8-sig")  # remove BOM se houver
        data = json.loads(txt)
    except Exception as exc:  # noqa: BLE001
        data = None
        err = f"falha de parse JSON: {exc}"
    return data, raw, err


def detectar_familia(data: Any) -> Tuple[str, Optional[int], Optional[str], Optional[str]]:
    """Retorna (familia, versao, file_type, nota). Nunca lança (R13)."""
    if not isinstance(data, dict):
        return "desconhecida", None, None, "raiz não é objeto JSON"
    ft = data.get("file_type") if isinstance(data.get("file_type"), str) else None
    ver = data.get("version") if isinstance(data.get("version"), (int, float)) else None
    tp = data.get("type") if isinstance(data.get("type"), str) else None

    if tp == "template" and "advantages" in data:
        return "template_legacy", ver, ft, "legacy v1/v2 (chave 'advantages')"
    if tp == "template" or ("traits" in data and ft is not None):
        return "template_moderno", ver, ft, "template com Header"
    if tp == "character":
        return "character_export", ver, ft, "export 'character' (.gcs.txt)"
    if "profile" in data and "attributes" in data:
        return "sheet_gcs", ver, ft, "save de ficha (.gcs)"
    if "ex" in data and "charName" in data:
        return "externo_singular", ver, ft, "formato externo (Singular/plataforma irmã)"
    return "desconhecida", ver, ft, "sem assinatura reconhecida"


# ---------------------------------------------------------------------------
# Normalizadores internos
# ---------------------------------------------------------------------------
def norm_feature(f: Dict[str, Any], avisos: Avisos) -> Dict[str, Any]:
    t = f.get("type")
    out: Dict[str, Any] = {"type": t, "raw": copy.deepcopy(f)}
    if t in FEATURES_KNOWN:
        out["mapeado"] = True
    else:
        out["mapeado"] = False
        avisos.add("warn", "feature_desconhecida", f"type={t!r} preservado cru (R2)")
    # valores numéricos comuns
    for k in ("amount", "percentage", "st", "base", "modifier_per_die"):
        if k in f:
            out[k] = numero(f[k]) if numero(f[k]) is not None else f[k]
            out[f"{k}_cru"] = f[k]
    if "per_level" in f:
        out["per_level"] = bool(f["per_level"])
    if "location" in f:
        out["location"] = f["location"]
    if "attribute" in f:
        out["attribute"] = f["attribute"]
    if "situation" in f:
        out["situation"] = f["situation"]
    if "match" in f:
        out["match"] = f["match"]
    if "name" in f and isinstance(f["name"], dict):
        out["selecao"] = f["name"]
    if "selection_type" in f:
        out["selection_type"] = f["selection_type"]
    if "level" in f and isinstance(f["level"], dict):
        out["level_filter"] = f["level"]
    if "weapon" in f and isinstance(f["weapon"], dict):
        out["weapon_filter"] = f["weapon"]
    return out


def norm_damage(d: Any, avisos: Avisos) -> Optional[Dict[str, Any]]:
    if d is None:
        return None
    if isinstance(d, str):
        return {"cru": d, "tipo": None, "st": None}
    out: Dict[str, Any] = {"cru": copy.deepcopy(d)}
    t = d.get("type")
    st = d.get("st")
    out["tipo"] = DANO_PT.get(t) if t else None
    out["tipo_original"] = t
    out["st"] = ST_PT.get(st) if st else None
    out["st_original"] = st
    if "base" in d:
        out["base"] = d["base"]
    if t and t not in DANO_PT:
        avisos.add("warn", "dano_desconhecido", f"código de dano {t!r} fora da tabela §18 (preservado cru)")
    if st and st not in ST_PT:
        avisos.add("warn", "modo_st_desconhecido", f"modo de ST {st!r} fora da tabela §18 (preservado cru)")
    return out


def norm_default(d: Any, avisos: Avisos) -> Dict[str, Any]:
    if not isinstance(d, dict):
        return {"cru": d}
    out: Dict[str, Any] = {"type": d.get("type"), "raw": copy.deepcopy(d)}
    nm = d.get("name")
    if isinstance(nm, str):
        out["alvo"] = {"compare": "is", "qualifier": nm}
    elif isinstance(nm, dict):
        out["alvo"] = {"compare": nm.get("compare", "is"), "qualifier": nm.get("qualifier")}
    for k in ("modifier", "specialization", "tag", "power_source"):
        if k in d:
            out[k] = d[k]
    out["modifier_num"] = numero(d.get("modifier"))
    return out


def norm_weapon(w: Any, avisos: Avisos) -> Dict[str, Any]:
    if not isinstance(w, dict):
        return {"cru": w}
    out: Dict[str, Any] = {"tipo": w.get("type"), "raw": copy.deepcopy(w)}
    simples = ("usage", "reach", "parry", "block", "accuracy", "range",
               "rate_of_fire", "shots", "recoil", "bulk", "strength", "sv", "fencing", "unbalanced")
    for k in simples:
        if k in w:
            out[k] = num_str(w[k]) if k in ("parry", "block", "accuracy", "strength", "sv") else w[k]
    if "damage" in w:
        out["dano"] = norm_damage(w["damage"], avisos)
    if "defaults" in w and isinstance(w["defaults"], list):
        out["defaults"] = [norm_default(x, avisos) for x in w["defaults"]]
    if "calc" in w:
        out["calc"] = w["calc"]
    return out


def norm_prereqs(p: Any, avisos: Avisos) -> Dict[str, Any]:
    if p is None:
        return {}
    if isinstance(p, list):
        return {"grupo": {"op": "nao_informado", "requisitos": [norm_prereqs(x, avisos) for x in p]},
                "cru": copy.deepcopy(p)}
    if not isinstance(p, dict):
        return {"cru": p}
    out: Dict[str, Any] = {"cru": copy.deepcopy(p)}
    if p.get("type") == "prereq_list" or "prereqs" in p:
        op = "all" if p.get("all") is True else ("any" if p.get("any") else "nao_informado")
        subs = p.get("prereqs") or []
        out["grupo"] = {
            "op": op,
            "requisitos": [norm_prereqs(x, avisos) for x in subs if isinstance(x, dict)],
        }
    else:
        tp = p.get("type")
        if tp and tp not in PREREQ_TIPOS_KNOWN:
            avisos.add("info", "pre_req_tipo_novo", f"type={tp!r} (preservado; adicionar à whitelist R2)")
        out["requisito"] = {k: v for k, v in p.items() if k != "type"}
        out["tipo"] = tp
    return out


def norm_item(node: Dict[str, Any], avisos: Avisos, profundidade: int = 0) -> Dict[str, Any]:
    """Normaliza uma vantagem/contêiner recursivamente (profundidade limita loops)."""
    if profundidade > 6:
        avisos.add("warn", "profundidade_excedida", "item com aninhamento >6 truncado")
        return {"cru": node}
    out: Dict[str, Any] = {"id": node.get("id"), "nome": node.get("name"), "raw_id": node.get("id")}
    for k in ("reference", "reference_highlight", "local_notes"):
        if k in node:
            out[k] = node[k]
    if "container_type" in node:
        out["container_type"] = node["container_type"]
    if "ancestry" in node:
        out["ancestry"] = node["ancestry"]
    # cálculo/custo
    custo: Dict[str, Any] = {}
    if "calc" in node and isinstance(node["calc"], dict):
        custo["calc"] = node["calc"]
    if "base_points" in node:
        custo["base_points"] = numero(node["base_points"])
        custo["base_points_cru"] = node["base_points"]
    if "points_per_level" in node:
        custo["points_per_level"] = numero(node["points_per_level"])
        custo["points_per_level_cru"] = node["points_per_level"]
    if "levels" in node:
        custo["levels"] = node["levels"]
        custo["levels_cru"] = node["levels"]
        custo["allow_half_levels"] = bool(node.get("allow_half_levels", False))
    if "round_down" in node:
        custo["round_down"] = bool(node["round_down"])
    if "cr" in node:
        custo["cr"] = node["cr"]
        if "cr_adj" in node:
            custo["cr_adj"] = node["cr_adj"]
    out["custo"] = custo
    # flags de classificação
    flags = {k: bool(node[k]) for k in ("physical", "mental", "social", "exotic", "supernatural") if k in node}
    if flags:
        out["flags"] = flags
    if "categories" in node and isinstance(node["categories"], list):
        out["categorias"] = node["categories"]
        out["categorias_lang"] = [lang_de(c) for c in node["categories"]]
    if "tags" in node:
        out["tags"] = node["tags"]
    if "notes" in node:
        out["notas"] = node["notes"]
    if "features" in node and isinstance(node["features"], list):
        out["features"] = [norm_feature(f, avisos) for f in node["features"] if isinstance(f, dict)]
    if "modifiers" in node and isinstance(node["modifiers"], list):
        mods = []
        for m in node["modifiers"]:
            if not isinstance(m, dict):
                continue
            mm = {"nome": m.get("name"), "raw": copy.deepcopy(m)}
            cc = numero(m.get("cost"))
            mm["custo"] = cc if cc is not None else m.get("cost")
            mm["custo_cru"] = m.get("cost")
            mm["cost_type"] = m.get("cost_type")
            if "affects" in m:
                mm["affects"] = m["affects"]
            if "reference" in m:
                mm["referencia"] = m["reference"]
            if "disabled" in m:
                mm["desabilitado"] = bool(m["disabled"])
                if m["disabled"]:
                    avisos.add("info", "mod_desabilitado", f"modificador '{m.get('name')}' desabilitado (mantido como opção off — R3)")
            if "notes" in m:
                mm["notas"] = m["notes"]
            if "features" in m and isinstance(m["features"], list):
                mm["features"] = [norm_feature(f, avisos) for f in m["features"] if isinstance(f, dict)]
            mods.append(mm)
        out["modificadores"] = mods
    if "weapons" in node and isinstance(node["weapons"], list):
        out["armas"] = [norm_weapon(w, avisos) for w in node["weapons"] if isinstance(w, dict)]
    if "prereqs" in node:
        out["pre_requisitos"] = norm_prereqs(node["prereqs"], avisos)
    if "children" in node and isinstance(node["children"], list):
        out["filhos"] = [norm_item(c, avisos, profundidade + 1) for c in node["children"] if isinstance(c, dict)]
    # qualquer chave não tratada fica registrada para auditoria (R9)
    tratados = {"id", "name", "reference", "reference_highlight", "local_notes", "container_type", "ancestry",
                "calc", "base_points", "points_per_level", "levels", "allow_half_levels", "round_down", "cr", "cr_adj",
                "physical", "mental", "social", "exotic", "supernatural", "categories", "tags", "notes", "features",
                "modifiers", "weapons", "prereqs", "children"}
    restantes = {k: v for k, v in node.items() if k not in tratados}
    if restantes:
        out["extras"] = restantes
    return out


# ---------------------------------------------------------------------------
# Montagem do template canônico (R1/R8/R9)
# ---------------------------------------------------------------------------
def canonizar_template(path: Path, data: Any, avisos: Avisos) -> Dict[str, Any]:
    fam, ver, ft, nota = detectar_familia(data)
    src_size = path.stat().st_size if path.exists() else 0
    canon: Dict[str, Any] = {
        "origem": {"arquivo": path.name, "bytes": src_size, "sha256": sha256_bytes(path.read_bytes()) if path.exists() else ""},
        "envelope": {"familia": fam, "familia_descricao": FAMILIAS.get(fam, fam), "versao_dados": ver, "file_type": ft, "nota": nota},
        "schema": "canonico.v0.7.2-draft",
    }
    if fam in ("sheet_gcs", "character_export", "externo_singular", "desconhecida"):
        canon["status"] = "fora_do_escopo"
        return canon
    if fam == "template_moderno":
        # dados diretos (TemplateData)
        canon.update({
            "id": data.get("id"),
            "nome": data.get("name"),
            "referencia": data.get("reference"),
            "reference_highlight": data.get("reference_highlight"),
            "local_notes": data.get("local_notes"),
            "target_points": data.get("target_points"),
            "ancestry": data.get("ancestry") if isinstance(data.get("ancestry"), str) else None,
            "status": "convertido",
        })
        lista_raiz = list(data.get("traits") or []) + list(data.get("advantages") or [])
        skills = data.get("skills") or []
    else:  # template_legacy
        lista_raiz = list(data.get("advantages") or [])
        skills = data.get("skills") or []
        # o nome/referência moram no container
        prim = lista_raiz[0] if lista_raiz else {}
        canon.update({
            "id": data.get("id"),
            "nome": prim.get("name") if isinstance(prim, dict) else None,
            "referencia": prim.get("reference") if isinstance(prim, dict) else None,
            "ancestry": prim.get("ancestry") if isinstance(prim, dict) and isinstance(prim.get("ancestry"), str) else None,
            "target_points": None,
            "status": "convertido",
        })
    if not canon.get("nome"):
        avisos.add("warn", "sem_nome", "template sem nome; usando rótulo do arquivo")
        canon["nome"] = path.stem
    # containers -> itens normalizados
    itens: List[Dict[str, Any]] = []
    for el in lista_raiz:
        if isinstance(el, dict):
            itens.append(norm_item(el, avisos))
    canon["itens"] = itens
    canon["skills_raiz"] = [
        {"nome": s.get("name"), "reference": s.get("reference"), "difficulty": s.get("difficulty"),
         "specialization": s.get("specialization"), "points": numero(s.get("points")),
         "defaults": [norm_default(d, avisos) for d in (s.get("defaults") or []) if isinstance(d, dict)],
         "categories": s.get("categories"), "tags": s.get("tags"), "raw": copy.deepcopy(s)}
        for s in skills if isinstance(s, dict)
    ]
    # contagens internas usadas no relatório
    cont = Counter()
    def conta(it: Dict[str, Any]) -> None:
        cont["itens"] += 1
        mods = it.get("modificadores") or []
        cont["mods_total"] += len(mods)
        cont["mods_desat"] += sum(1 for m in mods if m.get("desabilitado"))
        # features contam nos DOIS lugares onde aparecem: itens e modificadores (metodo B, doc §7)
        feats = list(it.get("features") or [])
        for m in mods:
            feats.extend(m.get("features") or [])
        cont["feats_total"] += len(feats)
        cont["feats_desconhecidas"] += sum(1 for f in feats if not f.get("mapeado"))
        cont["armas"] += len(it.get("armas") or [])
        cont["pre_reqs"] += 1 if it.get("pre_requisitos") else 0
        for filho in it.get("filhos") or []:
            conta(filho)
    for it in itens:
        conta(it)
    cont["roots"] = len(itens)                          # conteineres-raiz (raca/meta) deste arquivo
    cont["itens_internos"] = cont["itens"] - cont["roots"]  # comparavel a analise das 181 vantagens
    for sk in canon["skills_raiz"]:
        cont["skills_raiz"] += 1
        cont["skills_defaults"] += len(sk.get("defaults") or [])
    canon["estatisticas_locais"] = dict(cont)
    # placeholders (R7) — vasculha texto livre
    corpo = json.dumps(data, ensure_ascii=False)
    ph = PLACEHOLDER_RE.findall(corpo)
    if ph:
        cont["placeholders"] = len(ph)
        avisos.add("info", "placeholders_presentes", f"{len(ph)} marcações @…@ preservadas cru (R7)")
    canon["estatisticas_locais"] = dict(cont)
    return canon


def canonizar_ficha(data, avisos, display, familia, ver, ft, nota, size, hashb):
    # Normaliza fichas completas (.gcs) e exports "character" (.gcs.txt) — fase 2 (R21/R22).
    perfil = data.get("profile") if isinstance(data.get("profile"), dict) else {}
    canon = {
        "origem": {"arquivo": display, "bytes": size, "sha256": hashb},
        "envelope": {"familia": familia, "familia_descricao": FAMILIAS.get(familia, familia),
                     "versao_dados": ver, "file_type": ft, "nota": nota},
        "schema": "canonico.v0.7.2-draft",
        "escopo": ESCOPO_FASE2,
        "status": "convertido",
        "id": data.get("id"),
        "nome": perfil.get("name") or None,
        "titulo": perfil.get("title") or None,
        "pontos_totais": numero(data.get("total_points")),
        "perfil": copy.deepcopy(perfil),
        "atributos": copy.deepcopy(data.get("attributes") or []),
        "calculo": copy.deepcopy(data.get("calc") or {}),
    }
    if not canon.get("nome"):
        avisos.add("warn", "sem_nome", "ficha sem nome de perfil; usando rótulo do arquivo")
        canon["nome"] = Path(display).stem.replace(".gcs", "").replace(".txt", "") or display
    raiz = list(data.get("advantages") or []) if familia == "character_export" else list(data.get("traits") or [])
    canon["itens"] = [norm_item(x, avisos) for x in raiz if isinstance(x, dict)]
    skills = data.get("skills") or []
    canon["skills_raiz"] = [
        {"nome": s.get("name"), "reference": s.get("reference"), "difficulty": s.get("difficulty"),
         "specialization": s.get("specialization"), "points": numero(s.get("points")),
         "defaults": [norm_default(d, avisos) for d in (s.get("defaults") or []) if isinstance(d, dict)],
         "categories": s.get("categories"), "tags": s.get("tags"), "raw": copy.deepcopy(s)}
        for s in skills if isinstance(s, dict)
    ]
    canon["equipamentos"] = [
        {"id": e.get("id"), "nome": e.get("name"), "quantidade": numero(e.get("quantity")),
         "equipado": bool(e.get("equipped")),
         "armas": [norm_weapon(w, avisos) for w in (e.get("weapons") or []) if isinstance(w, dict)],
         "raw": copy.deepcopy(e)}
        for e in (data.get("equipment") or []) if isinstance(e, dict)
    ]
    canon["notas"] = copy.deepcopy(data.get("notes") or [])
    # contagens espelhando o contador dos templates (mesma métrica B do §7)
    cont = Counter()

    def conta(it):
        cont["itens"] += 1
        mods = it.get("modificadores") or []
        cont["mods_total"] += len(mods)
        cont["mods_desat"] += sum(1 for m in mods if m.get("desabilitado"))
        feats = list(it.get("features") or [])
        for m in mods:
            feats.extend(m.get("features") or [])
        cont["feats_total"] += len(feats)
        cont["feats_desconhecidas"] += sum(1 for f in feats if not f.get("mapeado"))
        cont["armas"] += len(it.get("armas") or [])
        cont["pre_reqs"] += 1 if it.get("pre_requisitos") else 0
        for filho in it.get("filhos") or []:
            conta(filho)

    for it in canon["itens"]:
        conta(it)
    cont["armas"] += sum(len(e.get("armas") or []) for e in canon["equipamentos"])
    cont["roots"] = len(canon["itens"])
    cont["itens_internos"] = cont["itens"] - cont["roots"]
    for sk in canon["skills_raiz"]:
        cont["skills_raiz"] += 1
        cont["skills_defaults"] += len(sk.get("defaults") or [])
    cont["equipamentos"] = len(canon["equipamentos"])
    cont["notas"] = len(canon["notas"])
    corpo = json.dumps(data, ensure_ascii=False)
    ph = PLACEHOLDER_RE.findall(corpo)
    if ph:
        cont["placeholders"] = len(ph)
        avisos.add("info", "placeholders_presentes", f"{len(ph)} marcações @…@ preservadas cru (R7)")
    canon["estatisticas_locais"] = dict(cont)
    return canon


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------
class Resultado:
    def __init__(self) -> None:
        self.canons: List[Dict[str, Any]] = []
        self.erros: List[str] = []
        self.aviso_por_arquivo: Dict[str, Avisos] = {}

    # ---------- entrada ----------
    def coletar_fontes(self, entradas):
        # Fontes: ('file', caminho, None) | ('zipentry', caminho_zip, nome_interno).
        # Aceita fase 1 (.gct) e fase 2 (.gcs/.gcs.txt/_gurps.json), inclusive dentro de ZIPs (R12/R13/R21).
        fontes = []

        def aceitar(nome):
            n = nome.lower()
            return any(n.endswith(sfx) for sfx in SUFIXOS_SUPORTADOS)

        for ent in entradas:
            pth = Path(ent)
            if pth.is_dir():
                for sfx in SUFIXOS_SUPORTADOS:
                    fontes += [("file", f, None) for f in sorted(pth.rglob("*" + sfx))]
            elif pth.is_file() and pth.suffix.lower() in SUFIXOS_SUPORTADOS:
                fontes.append(("file", pth, None))
            elif pth.is_file() and pth.suffix.lower() == ".zip":
                with zipfile.ZipFile(pth) as z:
                    for zi in z.infolist():
                        if aceitar(zi.filename):
                            fontes.append(("zipentry", pth, zi.filename))
            else:
                self.erros.append(f"entrada ignorada (tipo não suportado): {ent}")
        # deduplica mantendo ordem
        vistos = set()
        unica = []
        for f in fontes:
            chave = (f[0], str(f[1]), f[2])
            if chave in vistos:
                continue
            vistos.add(chave)
            unica.append(f)
        return unica

    def importar(self, fontes):
        cache_zips = {}
        for kind, pth, inner in fontes:
            display = pth.name if kind == "file" else f"{pth.name}!{inner}"
            try:
                if kind == "file":
                    data, raw, err = ler_arquivo(pth)
                    if err:
                        self.erros.append(f"{display}: {err}")
                        continue
                    size = pth.stat().st_size
                    hashb = sha256_bytes(raw)
                else:
                    if pth not in cache_zips:
                        with zipfile.ZipFile(pth) as z:
                            cache_zips[pth] = {n: z.read(n) for n in z.namelist()
                                               if any(n.lower().endswith(s) for s in SUFIXOS_SUPORTADOS)}
                    raw = cache_zips[pth][inner]
                    data = json.loads(raw.decode("utf-8-sig"))
                    size = len(raw)
                    hashb = sha256_bytes(raw)
                avisos = Avisos()
                fam, ver, ft, nota = detectar_familia(data)
                if fam in CONJ_FORA:
                    avisos.add("warn", "fora_do_escopo", f"família {fam!r} não pertence às famílias suportadas (R13)")
                    canon = {"origem": {"arquivo": display, "bytes": size, "sha256": hashb},
                             "envelope": {"familia": fam, "versao_dados": ver, "file_type": ft, "nota": nota},
                             "status": "fora_do_escopo", "escopo": ESCOPO_FORA}
                elif fam in CONJ_FASE2:
                    canon = canonizar_ficha(data, avisos, display, fam, ver, ft, nota, size, hashb)
                else:
                    canon = canonizar_template_proxy(Path(inner or pth.name), data, avisos, size, hashb)
                    canon["origem"]["arquivo"] = display
                    canon["escopo"] = ESCOPO_FASE1
                self.canons.append(canon)
                self.aviso_por_arquivo[display] = avisos
            except Exception as exc:  # noqa: BLE001 — nunca estourar (R6)
                self.erros.append(f"{display}: exceção inesperada: {exc}")


def canonizar_template_proxy(path: Path, data: Any, avisos: Avisos, size: int, hashb: str) -> Dict[str, Any]:
    """Variação para entradas de ZIP (usa metadados fornecidos em vez de tocar disco)."""
    canon = canonizar_template(path, data, avisos)
    canon["origem"] = {"arquivo": path.name, "bytes": size, "sha256": hashb}
    return canon


# ---------------------------------------------------------------------------
# Relatório (R8)
# ---------------------------------------------------------------------------
ESCOPO_AMIGAVEL = {ESCOPO_FASE1: "fase 1", ESCOPO_FASE2: "fase 2", ESCOPO_FORA: "—"}


def _rotulo_tipologia(c):
    if c.get("escopo") == ESCOPO_FASE2:
        return "ficha" if c["envelope"].get("familia") == "sheet_gcs" else "personagem"
    return "raça" if (c.get("ancestry") or (c.get("itens") and c["itens"][0].get("container_type") == "race")) else "meta"


def render_relatorio(res: Resultado, out_dir: Path) -> str:
    linhas_ok = [c for c in res.canons if c.get("status") == "convertido"]
    linhas_out = [c for c in res.canons if c.get("status") != "convertido"]
    total_arquivos = len(res.canons)
    agg: Counter = Counter()
    per_file_rows: List[Dict[str, Any]] = []
    for c in linhas_ok:
        loc = c.get("estatisticas_locais", {})
        agg["itens"] += loc.get("itens", 0)
        agg["roots"] += loc.get("roots", 0)
        agg["mods_total"] += loc.get("mods_total", 0)
        agg["mods_desat"] += loc.get("mods_desat", 0)
        agg["feats_total"] += loc.get("feats_total", 0)
        agg["feats_desconhecidas"] += loc.get("feats_desconhecidas", 0)
        agg["armas"] += loc.get("armas", 0)
        agg["skills_raiz"] += loc.get("skills_raiz", 0)
        agg["skills_defaults"] += loc.get("skills_defaults", 0)
        agg["placeholders"] += loc.get("placeholders", 0)
        agg["pre_reqs"] += loc.get("pre_reqs", 0)
        agg["equipamentos"] += loc.get("equipamentos", 0)
        agg["notas"] += loc.get("notas", 0)
        per_file_rows.append({
            "nome": c.get("nome"), "ref": c.get("referencia"),
            "tipo": _rotulo_tipologia(c),
            "versao": c["envelope"].get("versao_dados"), "familia": c["envelope"].get("familia"),
            "itens": loc.get("itens", 0),
            "escopo": ESCOPO_AMIGAVEL.get(c.get("escopo"), ""),
        })
    codigos: Counter = Counter()
    for av in res.aviso_por_arquivo.values():
        codigos += av.contagem()
    f1 = [c for c in linhas_ok if (c.get("escopo") or ESCOPO_FASE1) == ESCOPO_FASE1]
    f2 = [c for c in linhas_ok if c.get("escopo") == ESCOPO_FASE2]
    md: List[str] = []
    md.append("# Relatório de importação — acervo GCS (.gct/.gcs/.gcs.txt)\n")
    md.append("> Gerado pelo `importador_gct.py` (referência v0.7.2 do kit Singular).\n")
    md.append("## Visão geral\n")
    md.append(f"- Arquivos processados: **{total_arquivos}**\n")
    md.append(f"- Convertidos: **{len(linhas_ok)}** (fase 1: **{len(f1)}** · fase 2: **{len(f2)}**) · Fora do escopo: **{len(linhas_out)}** · Erros fatais: **{len(res.erros)}**\n")
    if agg.get("equipamentos") or agg.get("notas"):
        md.append(f"- Equipamentos: **{agg.get('equipamentos', 0)}** · Notas de ficha: **{agg.get('notas', 0)}**\n")
    md.append(f"- Itens (**todos os níveis, recursivo**): **{agg['itens']}** — "
              f"**{agg['roots']}** contêineres-raiz + **{agg['itens'] - agg['roots']}** itens internos\n")
    md.append(f"- Modificadores: **{agg['mods_total']}** (desabilitados mantidos como opção: **{agg['mods_desat']}**)\n")
    md.append(f"- Features: **{agg['feats_total']}** (desconhecidas preservadas cru: **{agg['feats_desconhecidas']}**)\n")
    md.append(f"- Armas: **{agg['armas']}** · Skills de raiz: **{agg['skills_raiz']}** · Defaults de skill: **{agg['skills_defaults']}**\n")
    md.append(f"- Pré-requisitos: **{agg['pre_reqs']}** · Placeholders `@…@`: **{agg['placeholders']}**\n")
    md.append("\n## Por arquivo\n")
    md.append("| Nome | Ref. | Tipo | Versão | Família | Itens | Escopo |\n|---|---|---:|---:|---|---:|---|\n")
    for r in sorted(per_file_rows, key=lambda x: str(x["nome"])):
        md.append(f"| {r['nome']} | {r['ref'] or ''} | {r['tipo']} | {r['versao']} | {r['familia']} | {r['itens']} | {r['escopo']} |\n")
    if codigos:
        md.append("\n## Avisos agrupados\n")
        md.append("| Código | Nível | Ocorrências |\n|---|---|---:|\n")
        nivel_map = {"mod_desabilitado": "info", "placeholders_presentes": "info", "pre_req_tipo_novo": "info"}
        for cod, n in codigos.most_common():
            nv = nivel_map.get(cod, "warn")
            desc = COD_DESC.get(cod, cod)
            md.append(f"| {cod} | {nv} | {n} |\n")
        md.append("\n**Legenda:**\n")
        for cod in codigos:
            if cod in COD_DESC:
                md.append(f"- `{cod}` — {COD_DESC[cod]}\n")
    if res.erros:
        md.append("\n## Erros\n")
        for e in res.erros:
            md.append(f"- {e}\n")
    if linhas_out:
        md.append("\n## Arquivos fora do escopo v0.7.2\n")
        for c in linhas_out:
            md.append(f"- `{c['origem']['arquivo']}` — família `{c['envelope']['familia']}`\n")
    return "\n".join(md)


COD_DESC = {
    "mod_desabilitado": "modificador marcado `disabled:true` — preservado como opção desmarcada (R3).",
    "placeholders_presentes": "marcações `@…@` — preservadas cru no texto (R7).",
    "pre_req_tipo_novo": "tipo de pré-requisito visto pela primeira vez — adicionado à observação, não bloqueia.",
    "feature_desconhecida": "feature fora da whitelist conhecida — armazenada crua para inspeção (R2).",
    "dano_desconhecido": "código de dano fora da tabela §18 — preservado cru (R22).",
    "modo_st_desconhecido": "modo de ST fora da tabela §18 — preservado cru (R22).",
    "sem_nome": "template sem nome no conteúdo — usou-se o rótulo do arquivo.",
    "fora_do_escopo": "arquivo não pertence às famílias suportadas na v0.7.2.",
    "profundidade_excedida": "aninhamento além do limite — trecho preservado cru.",
    "version_sob_aviso": "versão acima da máxima testada — importado tentando (R15).",
}


def contar_por_tipo(res: Resultado) -> Counter:
    c: Counter = Counter()
    for canon in res.canons:
        if canon.get("status") != "convertido":
            continue
        if canon.get("escopo") == ESCOPO_FASE2:
            c["ficha" if canon["envelope"].get("familia") == "sheet_gcs" else "personagem"] += 1
        else:
            c["raça" if canon.get("ancestry") else "meta"] += 1
    return c


# ---------------------------------------------------------------------------
# Escritas de saída
# ---------------------------------------------------------------------------
def salvar_saídas(res: Resultado, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    can_dir = out_dir / "canonicos"
    can_dir.mkdir(exist_ok=True)
    usados: Counter = Counter()
    for canon in res.canons:
        nome = canon.get("nome") or canon["origem"]["arquivo"]
        s = slug(str(nome))
        if usados[s]:
            s = f"{s}_{usados[s]}"
        usados[s] += 1
        p = can_dir / f"{s}.json"
        p.write_text(json.dumps(canon, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    rel = render_relatorio(res, out_dir)
    (out_dir / "relatorio_importacao.md").write_text(rel, encoding="utf-8")


# ---------------------------------------------------------------------------
# Selftest (fixture congelado — R10)
# ---------------------------------------------------------------------------
def selftest(alvos):
    ok = True
    print("== SELFTEST importador_gct ==")
    res = Resultado()
    vistos = set()
    for alvo in alvos:
        fs = res.coletar_fontes([alvo])
        for kind, pth, inner in fs:
            vistos.add(Path(inner or pth.name).name)
        res.importar(fs)
    converted = [c for c in res.canons if c.get("status") == "convertido"]
    f1 = [c for c in converted if (c.get("escopo") or ESCOPO_FASE1) == ESCOPO_FASE1]
    f2 = [c for c in converted if c.get("escopo") == ESCOPO_FASE2]
    checks = []

    def ad(label, passed, extra=""):
        checks.append((label, bool(passed), str(extra)))

    # ---- Suíte A: corpus .gct (fixture congelado) ----
    gcts = [n for n in vistos if n.lower().endswith(".gct")]
    if gcts:
        ad("arquivos .gct encontrados", len(gcts) > 0, f"{len(gcts)}")
        ad("zero erros fatais", len(res.erros) == 0, "; ".join(res.erros[:3]) or "nenhum")
        ad("todos os .gct convertidos", len(f1) >= len(gcts), f"{len(f1)}/{len(gcts)}")
        if len(f1) == 23:
            tipos = contar_por_tipo(res)
            ad("5 raças", tipos.get("raça", 0) == 5, f"{tipos.get('raça', 0)}")
            ad("18 meta-características", tipos.get("meta", 0) == 18, f"{tipos.get('meta', 0)}")
            somas = Counter()
            for c in f1:
                loc = c.get("estatisticas_locais", {})
                somas["itens"] += loc.get("itens", 0)
                somas["roots"] += loc.get("roots", 0)
                somas["mods_total"] += loc.get("mods_total", 0)
                somas["feats_total"] += loc.get("feats_total", 0)
            internos = somas["itens"] - somas["roots"]
            ad(f"itens internos == 181 (exclui {somas['roots']} raízes)", internos == 181, f"{internos}")
            ad("soma de modificadores == 867", somas["mods_total"] == 867, f"{somas['mods_total']}")
            ad("features == 212 (itens+modificadores; medido fixture v1)", somas["feats_total"] == 212, f"{somas['feats_total']}")
        ids = [c.get("id") for c in f1]
        ad("ids únicos", len(set(ids)) == len(ids), f"{len(ids)}")
        ad("todos com nome", len([c for c in f1 if not c.get("nome")]) == 0, "—")
    else:
        ad("suíte A (corpus .gct)", True, "SKIP — nenhum .gct no alvo")

    # ---- Suíte B: amostras adicionais (.gcs / .gcs.txt) ----
    esperadas = {
        "Little Mouse.gcs": {"skills": 5, "itens_min": 5},
        "PC - Kadda La.gcs": {"skills": 14, "itens_min": 13},
        "Twig-Eater.gcs": {"skills": 9, "itens_min": 3},
        "Wooly Rhino.gcs": {"skills": 2, "itens_min": 14},
        "Homem-Zebra-PT.gcs.txt": {"skills": 13, "itens_min": 17, "equip": 4},
    }
    presentes = [n for n in esperadas if n in vistos]
    if presentes:
        ad("amostras adicionais detectadas", True, f"{len(presentes)}/{len(esperadas)}")
        for fn, exp in esperadas.items():
            if fn not in vistos:
                ad(f"{fn}", True, "SKIP")
                continue
            c = next((k for k in converted if k["origem"]["arquivo"].endswith(fn)), None)
            ad(f"{fn} convertida", c is not None, "—" if c else "não encontrada")
            if c:
                loc = c.get("estatisticas_locais", {})
                if "skills" in exp:
                    ad(f"{fn}: skills de raiz == {exp['skills']}", len(c.get("skills_raiz") or []) == exp["skills"], f"{len(c.get('skills_raiz') or [])}")
                if "itens_min" in exp:
                    ad(f"{fn}: itens >= {exp['itens_min']}", loc.get("itens", 0) >= exp["itens_min"], f"{loc.get('itens', 0)}")
                if "equip" in exp:
                    ad(f"{fn}: equipamentos == {exp['equip']}", len(c.get("equipamentos") or []) == exp["equip"], f"{len(c.get('equipamentos') or [])}")
        ad("zero erros nas amostras", len(res.erros) == 0, "; ".join(res.erros[:3]) or "nenhum")
    else:
        ad("suíte B (amostras adicionais)", True, "SKIP — nenhuma amostra no alvo")

    for label, passed, extra in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {label} — {extra}")
        ok = ok and passed
    print("resultado:", "OK" if ok else "COM FALHAS")
    return ok



# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("entradas", nargs="+", help="arquivos .gct/.gcs/.gcs.txt/.json, pastas ou zip")
    ap.add_argument("--out", default="out_importador", help="diretório de saídas")
    ap.add_argument("--selftest", action="store_true", help="roda checagens contra o fixture congelado")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return 0 if selftest(list(args.entradas)) else 1

    res = Resultado()
    fontes = res.coletar_fontes(args.entradas)
    res.importar(fontes)
    salvar_saídas(res, Path(args.out))

    if not args.quiet:
        for c in res.canons:
            if c.get("status") == "convertido":
                loc = c.get("estatisticas_locais", {})
                marcar = "" if c.get("escopo") == ESCOPO_FASE1 else " [fase2]"
                print(f"[ok]{marcar} {c['origem']['arquivo']} — {c.get('nome')} ({c.get('referencia') or '—'}) · "
                      f"{loc.get('itens', 0)} itens · {loc.get('mods_total', 0)} mods ({loc.get('mods_desat', 0)} desat.) · "
                      f"{loc.get('armas', 0)} armas")
            else:
                print(f"[--] {c['origem']['arquivo']} — fora do escopo ({c['envelope']['familia']})")
        for e in res.erros:
            print(f"[ERR] {e}")
        tipos = contar_por_tipo(res)
        ext2 = ""
        if tipos.get("ficha") or tipos.get("personagem"):
            ext2 = f" + {tipos.get('ficha', 0)} fichas, {tipos.get('personagem', 0)} personagens"
        print(f"\nResumo: {sum(tipos.values())} convertidos ({tipos.get('raça', 0)} raças, {tipos.get('meta', 0)} metas{ext2}); "
              f"{len(res.canons) - sum(tipos.values())} fora do escopo; {len(res.erros)} erros.")
        print(f"Saídas em: {Path(args.out).resolve()}")
    return 0 if not res.erros else 2


if __name__ == "__main__":
    sys.exit(main())
