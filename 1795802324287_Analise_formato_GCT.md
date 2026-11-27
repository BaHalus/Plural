# Análise do formato `.gct` — pacote "Raças e Metas"

> **Objetivo deste documento:** servir de referência de calibração para o importador de `.gct` previsto na v0.7.2 do kit Singular (raças e meta-características do GURPS 4e). Toda afirmação abaixo foi verificada sobre os **23 arquivos reais** do pacote anexado — não há suposição marcada como fato; o que ficou em aberto está listado no §13.

> **Atualização (27/11/2026):** a origem do formato foi confirmada — trata-se de exports do **GCS — GURPS Character Sheet** ([github.com/richardwilkes/gcs](https://github.com/richardwilkes/gcs)), mantido por Richard A. Wilkes. Detalhes e implicações no **§14**. No mesmo dia, o guia oficial foi lido e aplicado ao importador (**§§15–§16**), e as amostras adicionais foram analisadas em **§17**; seguem o glossário de equivalências (**§18**) e o contexto do ecossistema (**§19**).

## 1. TL;DR

- Um arquivo `.gct` é um **export JSON legível** (UTF-8, indentado com tab) contendo **um template**: uma **raça** (`container_type: "race"`) ou uma **meta-característica** (`"meta_trait"`).
- Gramática recursiva e pequena: `template → advantage_container → advantage → modifiers/features/weapons/prereqs`. Só **5 tipos principais** aparecem em toda a árvore (`template`, `advantage_container`, `advantage`, `modifier`, `skill`), com **subtipos de efeito** bem delimitados (atributo, DR, habilidade, reação, magia, custo reduzido etc.).
- Os **nomes de arquivo/pasta chegaram corrompidos** (encoding), mas o **conteúdo interno está íntegro** — cada arquivo guarda seu nome legítimo no campo `name`. Já produzi um ZIP renomeado e um catálogo CSV (ver §2).
- Recomendação central para o importador: **nunca confiar no nome do arquivo**; usar UUIDs internos como chave de deduplicação; política "reconheço → converto; não reconheço → guardo bruto + aviso" (tolerância já prevista na arquitetura).

## 2. Integridade e nomes dos arquivos

O pacote original tem 23 entradas **.JSON válidas em 23/23** (parse sem erro). O problema estava apenas nos metadados dos nomes: as pastas `Raças/` e `Metacaracterísticas/` e os nomes foram gravados **sem a flag de UTF-8**, com bytes interpretados pela página de código errada — daí coisas como `Ra嘺s/An苚.gct` no lugar de `Raças/Anão.gct`.

Corrigi isso recuperando o **nome legítimo direto do conteúdo** (campo `name` do container — ex.: `"Metacaracterística: Corpo de Água"`) e reconstruí o pacote:

| Entregável | Conteúdo | Validação feita |
|---|---|---|
| `Racas_Metas_nomes_corrigidos.zip` | Mesmo conteúdo **byte-a-byte** dos originais, com nomes/pastas corretos e flag UTF-8 ativa (bit 11 confirmado) | `testzip()` limpo; lista igual à esperada; comparação byte-a-byte contra o original: **0 divergências** |
| `catalogo_gct.csv` | Uma linha por arquivo: categoria, nome, referência bibliográfica, pontos do `calc`, nº de itens na pasta, skills na raiz, contagem de armas/DR/bônus/pré-requisitos, mods desabilitados e caminho do arquivo | Gerado programaticamente a partir do ZIP; 23 linhas |
| `Analise_formato_GCT.md` | Este documento | Conferência por leitura/grep das seções após geração |

Caminho alternativo: os arquivos também ficaram explodidos (legíveis) em `racas_metas/corrigidos/`.

## 3. Estrutura de raiz

Todos os 23 arquivos têm a mesma forma mínima:

```json
{
    "type": "template",            // sempre literal "template"
    "version": 2,                  // sempre 2 neste corpus
    "id": "<UUID>",                // chave estável do template
    "advantages": [ /* 1 container */ ],
    "skills": [ /* opcional; só 2 arquivos */ ]
}
```

- Chaves possíveis na raiz: `advantages`, `id`, `skills`, `type`, `version` (união observada; nada além disso).
- `skills` presente em **2/23**: Dragão (Básico) e Elfo.
- Todos os `open` internos são `true` (containers abertos no editor de origem).

### Árvore de referência

```
template
└─ advantages[0] = advantage_container        (race | meta_trait)
   ├─ name / reference / calc.points / ancestry(race)
   └─ children[]: advantage…                  (sempre type="advantage")
      ├─ modifiers[]: modifier                (custo, atributos, etc.)
      ├─ features[]: attribute_bonus | skill_bonus | dr_bonus | …
      ├─ weapons[]: melee_weapon | ranged_weapon
      ├─ prereqs: prereq_list → advantage_prereq
      └─ calc / flags / categories / notes / levels…
└─ skills[]?: skill                           (só nas raízes citadas)
```

Contagem total de objetos no corpus (útil para dimensionar testes): **181 vantagens, 867 modificadores, 98 `dr_bonus`, 44 `skill_bonus`, 31 `reaction_bonus`, 25 `attribute_bonus`, 26 skills, 12 `cost_reduction`, 9 armas corpo a corpo, 2 armas à distância.**

## 4. Container: raça × meta-característica

| | `race` (5 arquivos) | `meta_trait` (18 arquivos) |
|---|---|---|
| `ancestry` | sempre presente, valor `"Human"` | ausente |
| `calc.points` | positivo (+35 a +260) | pode ser negativo (−100 a +261) |
| `children` | 5–24 itens | 2–14 itens |
| Demais campos | idênticos | idênticos |

Campos do container (todos os 23): `type`, `id`, `container_type`, `name`, `reference`, `calc{points}`, `open`, `children`. Adicionalmente `ancestry` nas 5 raças.

Os valores de `reference` apontam para o módulo impresso: `B261`/`B262` (Basic Set — raças e metas), `B263` (metas diversas), `B316` (Elfos). Confira a tabela completa no **Apêndice A**.

## 5. Vantagens internas (`advantage`) — 181 instâncias

**Chaves sempre presentes:** `type`, `id`, `name`, `calc`.  
**Chaves opcionais com frequência observada:** `physical`(153), `categories`(166), `reference`(178), `base_points`(100), `modifiers`(94), `exotic`(102), `features`(29), `mental`(33), `supernatural`(9), `social`(1), `points_per_level`(35), `levels`(35), `round_down`(11), `cr`(6), `allow_half_levels`(1), `prereqs`(6), `weapons`(9), `notes`(27).

Pontos relevantes:

- **Duas formas de custo:** `base_points` (custo fixo) **ou** `levels` + `points_per_level` (custo por nível; `levels` vem como *string*, ex. `"1"`, `"5"`, `"0.5"`, inclusive meio-nível via `allow_half_levels`). O `calc` agrega o resultado (para o template/container vale sempre `{ "points": N }`).
- **Flags booleanas** que classificam a vantagem: `physical`/`mental`/`social`/`exotic`/`supernatural`. Podem coexistir no mesmo item.
- `categories` mistura rótulos em **PT e EN**: `Vantagem`, `Desvantagem`, `Qualidade`, `Talento`, `Advantage`, `Disadvantage`, `Combate Corpo a Corpo`, `Combate/Arma`, `Conhecimento`, `Social` etc. Guarde cru; mapeie depois.
- `calc` da própria vantagem reflete o custo atual (inclusive `0` para ajustes derivados, ex. sub-bônus cujo custo entra na conta do pacote).
- `notes` (27 casos) é texto longo PT explicando regra; útil mostrar ao usuário como tooltip/nota.

## 6. Modificadores (`modifier`) — 867 instâncias

**Sempre presentes:** `type`, `id`, `name`, `cost`, `cost_type`.  
**Opcionais:** `reference`(843), `affects`(794), `notes`(392), `disabled`(764), `features`(42), `levels`(42).

- `cost_type` ∈ `{ "points", "percentage", "multiplier" }`; `cost` é numérico (pode ser 0, negativo ou percentual, ex. `100`); `affects` ∈ `{ "total", "levels_only" }`.
- `reference` aponta para a entrada básica (**B15/B19/B85/B156**…), exibida junto ao nome.
- **Campo crítico `disabled`:** quando presente, vale **sempre `true`** (764 casos; nenhum `false`; ausência = ativo). Isto é, quase todo ajuste veio **desmarcado no exportador** — trata-se do comportamento típico desses apps (opções/livros alternativos desligados). O importador deve **preservar esse estado** e não aplicar esses custos/efeitos por padrão; idealmente oferecer no UI "mostrar opções alternativas desta raça/meta".
- `features` dentro de `modifier` agrupa bônus derivados sob um único ponto de custo (ex. `MT -1` → `feature: attribute_bonus sm -1`).
- `notes` é usado para explicar funcionamento; `situation` aparece nos `reaction_bonus` (ver §7).

## 7. Bônus tipados (`features` e afins)

Chaves por tipo (observado no corpus; todos com `type` literal):

| Tipo | Instâncias | Campos | Observações |
|---|---:|---|---|
| `attribute_bonus` | 25 | `amount`, `attribute`, `per_level?` | Atributos vistos: `dx ht iq(perception…) will fsm hp sm block dodge parry hearing taste_smell fright_check`. `fright_check` = "teste de pavor" |
| `dr_bonus` | 98 | `amount`, `location`, `per_level` | Localizações: `arm brain face fin foot groin hand leg neck skull tail torso vitals wing` |
| `skill_bonus` | 44 | `amount`, `name{name,compare,qualifier}`, `selection_type`, `per_level` | Seleciona habilidades por nome (`contains`/`is`/`starts_with`) — ex. "todas as perícias de Ladronagem" |
| `reaction_bonus` | 31 | `amount`, `per_level`, `situation` | Contextos sociais/negociais (12 textos distintos; inclui variante em EN: `"from others"`) |
| `spell_bonus` | 2 | `amount`, `per_level`, `match:"all_colleges"` | Colégio mágico genérico |
| `weapon_bonus` | 1 | `amount`, `level(name)`, `name{name,…}`, `selection_type`, `per_level` | Bônus a armas específicas; `level` aceita `{compare:"at_least", qualifier:N}` |
| `cost_reduction` | 12 | `attribute`, `percentage` | Redução % de custo de ST/DX etc. (muito em máquina/animal/veículo) |
| `dx` / `iq` | 12 / 1 | `modifier` | Referências rápidas a atributo com delta |
| `corte` / `perf` / `cont` / `qmd` | 6/2/1/2 | `st`, `base`, `modifier_per_die` | Objetos de **tipo de dano** usados em armas (§8) |

## 8. Armas

Dentro de `advantage.weapons[]`:

```json
{
    "type": "melee_weapon",
    "damage": { "type": "perf", "st": "thr", "base": "-1" },
    "usage": "Mordida", "reach": "C", "parry": "Não", "block": "Não",
    "calc": { "level": 0, "parry": "Não", "block": "Não", "damage": "thr-1 perf" },
    "defaults": [ { "type": "skill", "name": "Briga" }, { "type": "dx" } ]
}
```

- Armas corpo a corpo (9): `reach` (`"C"`, `"C,1"`), `parry`/`block` (`"Não"` ou número em string), `damage` tipado (`corte`, `perf`, `cont`), e a versão **string** em `calc.damage` (`"thr corte"`, `"thr-1 perf"`, `"thr (+1 per die) cont"`).
- Armas à distância (2 — Baforada do Dragão e um projétil de Corpo de Fogo): adicionam `accuracy:"3"`, `range:"20/2"` ou `"100/10"`, `rate_of_fire:"1"`, `shots:"3/dia"` (ou `"3"`), `recoil:"1"`; `damage.type: "qmd"` (quilometria/municiária — ex. `"1d"`).
- `defaults[]` define a **rota padrão de uso**: `skill` (por nome, podendo ter `specialization` e `modifier`) ou `dx`/`iq` com `modifier` numérico. É o que liga a arma às skills da ficha (ex. Briga/Ataque Inato no Dragão).
- Números podem vir como **string** mesmo em campos calculados (`"3"`, `"0"`); interpretar numericamente com flexibilidade.

## 9. Pré-requisitos

```json
"prereqs": {
    "type": "prereq_list", "all": true,
    "prereqs": [ { "type": "advantage_prereq", "has": false,
                   "name": { "compare": "is", "qualifier": "gagueira" } } ]
}
```

- `prereq_list.all` = verdadeiro quando TODOS sub-préreques precisam valer.
- `advantage_prereq.has` = `true` exige possuir; `false` exige **não** possuir (usado em Animal Doméstico para gagueira).
- `name` é qualificador comparado por `is` (exatidão textual, em PT).

## 10. Skills na raiz

Presentes em Dragão (2) e Elfo (1):

```json
{ "type": "skill", "id": "…uuid…", "name": "Connoisseur", "reference": "B192",
  "specialization": "Ambientes Naturais", "difficulty": "iq/a", "points": 1,
  "defaults": [ { "type": "iq", "modifier": -5 } ],
  "categories": ["Artes/Entretenimento", "Conhecimento", "Social"] }
```

- `difficulty` usa notação do GURPS: `"dx/e"`, `"iq/a"` (fácil/especializado).
- Há variantes sem `id` (skills dentro de `defaults`) — tratar `id` como opcional.
- Habilidades vêm com nomes em PT (Briga, Ataque Inato) intercalados com nomes em EN quando especializado fora do manual traduzido.

## 11. Convenções de texto (importante para parser tolerante)

1. **Idioma misto:** conteúdo majoritariamente PT-BR (traduzido por fãs), com resquícios de EN (`Advantage`/`Disadvantage`, `from others`, `Thrust/Cutting` implícito em siglas como `thr`). Não assumir idioma.
2. **Placeholders `@…@`:** 169 ocorrências em nomes/notas (`"@Comum: Venenos, Enjoos, etc.@"`, `"Amplia @Habilidade@"`) — marcas de substituição do app de origem. Decidir política: preservar cru, converter para `{variavel}` ou ignorar; documentar escolha.
3. **Strings numéricas:** níveis, alcances e contagens frequentemente em string (`"0.5"`, `"3/dia"`). Conversão defensiva obrigatória.
4. **Referências:** `B###` (basic), com pontuação ocasionalmente inconsistente. Exibir como citação, não validar.
5. **Texto livre em PT** de qualidade alta em `notes`/`situation` — aproveitar como documentação de regra no UI.

## 12. Recomendações para o importador (v0.7.2)

Diretas ao ponto, pensadas para o desenho "parsers tolerantes com fallback honesto":

- **R1 — Fonte da verdade é o conteúdo.** Ignorar totalmente o nome do arquivo; extrair nome real do `container.name` e tipo de `container_type`. Usar UUID (`template.id`, `container.id`, `advantage.id`, `modifier.id`) como chave primária para criar/atualizar com idempotência.
- **R2 — Subtipos com whitelist aberta.** Reconhecer os tipos conhecidos da §5–§10 e **nunca quebrar** em tipo/enum desconhecido: cair para armazenamento bruto (`raw`) + gerar aviso "item X preservado como dado original (não mapeado)". Isso protege contra novas versões do exportador.
- **R3 — `disabled` importa.** Converter `disabled:true` como opção desmarcada (custo zerado, efeito off) e registrar contagem no resumo de importação ("N ajustes alternativos desmarcados"). Nunca descartar silenciosamente.
- **R4 — Duas representações de custo.** Fixo (`base_points`) vs progressivo (`levels`×`points_per_level`) — suportar ambas e refletir em `calc`; aceitar `levels` fracionário e meio-nível.
- **R5 — Armas com dualidade obj/string.** Aceitar `damage` como objeto tipado OU ler a cordão do `calc.damage`; `defaults[]` mapeia para skills existentes por nome (com fuzzy leve p/ PT/EN); se não achar a skill, criar referência pendurada e avisar.
- **R6 — Números defensivos.** Parse int/float/string unificado ("3"→3, "3/dia"→3 com sufixo salvo, "0.5"→0.5). Sem exceção não-crash.
- **R7 — Placeholders e idiomas.** `@texto@` deve sobreviver intacto no texto (evita corrupção de contexto) com opção de sanitização posterior. Labels de `categories` preservados crus + tag de idioma detectada heuristicamente (pt/en).
- **R8 — Resumo pós-importação obrigatório.** Mostrar: quantos convertidos, quantos por grupo (raças/metas), desabilitados, avatares desconhecidos, pré-requisitos lidos, armas ligadas/não ligadas. Transparência > perfeição silenciosa.
- **R9 — Round-trip seguro.** Manter cópia canônica do JSON original por item (blob), permitindo re-export fiel e diagnóstico futuro.
- **R10 — Fixture de testes.** Congelar os 23 arquivos deste pacote como fixtures do projeto; qualquer mudança estrutural futura gera diff visível nos testes.
- **R11 — Deduplicação entre fontes.** Antes de criar duplicado de uma raça/meta já existente (mesmo UUID ou mesmo nome+referência), perguntar "atualizar ou manter dois?". Política do dono dos dados (27/11): **sempre perguntar ao usuário** — nunca decidir sozinho.
- **R12 — Importar pelo arquivo explodido.** Para inspeção humana, usar `racas_metas/corrigidos/`; para testes automatizados, consumir o ZIP renomeado (validado byte-a-byte).

- **R13 — Tolerar os dois envelopes de arquivo.** Formato legado (nosso corpus): JSON começando direto em `"type": "template"`; formato atual do GCS: cabeçalho `{"file_type": "...", "version": N}` em posição livre no topo. Detectar sem exigir; nunca recusar por membro desconhecido no topo; se `version` maior que a máxima testada (5), importar tentando com aviso destacado.
- **R14 — Espelhar a escrita do GCS.** Normalizar/re-salvar com indentação TAB, chaves determinísticas e newline final (`\n`) — o mesmo padrão verificado nos 23 originais (23/23), garantindo round-trip limpo (reforço do R9).
- **R15 — Versionamento suave.** Escalonar severidade inspirado no validador oficial: `version < 2` → alerta forte + heurística; `2..5` → caminho normal; `version > 5` → aviso "formato mais novo que a base analisada" + preservação crua do que não entender. Nunca perder dado por número de versão.

- **R16 — Placeholders `@…@` são estrutura, não sujeira.** Preservar integralmente (código puro ou forma legível); nunca traduzir/remover automaticamente; se oferecer preenchimento, seguir a semântica oficial («not set» repete a pergunta; «empty» apaga).
- **R17 — Estados fiéis ao original.** Registrar enabled/disabled/preconfigured/switched-on como vierem; só contabilizar pontos/efeitos do que estiver ON; apresentar o OFF como variante disponível (oficial: desabilitado não dá pontos, features nem ataques — refino do R3).
- **R18 — Choices ficam para a fase 2.** Containers de escolha (regras Count/Points/Value/Weight, “Picked as a Unit”, pick obrigatório) não aparecem no corpus atual; implementar depois dos containers simples, com fixture dedicado.
- **R19 — Normalização com dupla grafia.** Suportar lado a lado a raiz legada (`advantages`) e a atual (`traits`/`skills`/`spells`/`equipment`/`notes`/`body_type` + header), conforme a tabela do §16; manter sempre o blob cru (R9).
- **R20 — Nome exato em pré-reqs e defaults.** As regras oficiais exigem correspondência de nome exata (ignorando caixa) — comparar com casefold + normalização Unicode leve e sinalizar ambiguidades em vez de adivinhar.
- **R21 — Reconhecer as 4 famílias de envelope por estrutura.** `.gct` legado (nosso corpus), `.gct`/dados atuais do GCS (header + chaves novas), `.gcs` v5 (raiz anônima de ficha) e `.gcs.txt` JSON "character" v2; nunca decidir por extensão nem exigir `file_type`.
- **R22 — Tabela de danos bilíngue (confirmada pelo dono do acervo).** Aplicar as equivalências da **§18** (`corte↔cut`, `perfuração/perf↔imp`, `perfurante/pa↔pi`, `contusão/cont↔cr`, `fadiga/fad↔fat`, `queimadura/qmd↔burn`, `GeB↔sw`, `GdP↔thr`); manter sempre o valor cru + idioma detectado; código desconhecido → aviso e preservação crua.
- **R23 — Dualidade nos defaults.** `defaults[].name` aceita string OU `{compare, qualifier}` (às vezes com `specialization` estruturada); normalizar para UMA forma interna já no parse.
- **R24 — Proveniência registrada.** Persistir `source{library, path, id}` e `tags[]` quando vierem; habilitam sync futura com bibliotecas e diagnóstico de duplicatas.

- **Status da implementação (27/11):** código referencial entregue em `importador_gct.py` — validado contra o fixture congelado (selftest: 23/23 convertidos, 181 itens internos, 867 modificadores, 212 features) e suporte **fase 2** (`.gcs`/`.gcs.txt`) adicionado e validado com as amostras reais (segunda suíte do selftest).

## 13. Limitações e perguntas em aberto

- Amostra **coberta:** raças básicas (B261/B262/B316) e metas comuns (B262/B263). **Fora do corpus:** template de personagem inteiro, vantagens genéricas isoladas, outros livros (`M`, `MA`, `PJ`…), itens com `cost_type` diferente. O parser deve ser testado com amostras adicionais antes de prometer cobertura geral.
- **App de origem — resolvido em 27/11:** é o GCS – GURPS Character Sheet (§14). Pendências remanescentes: qual build/configuração gerou **este lote** (marcas `@…@` e tradução PT indicam ajustes de usuário) e cobertura de outras fontes — as amostras recebidas em 27/11 (saves `.gcs`, transcrição `.gcs.txt` e export `_gurps.json`) já estão incorporadas no **§17**; seguir ampliando fixtures conforme novos pacotes chegarem (R10).
- Representação interna no Singular: a semântica oficial de `disabled` (sem pontos/features/ataques), dos placeholders (`@…@`) e dos custos progressivos (`levels`×`points_per_level`) já está registrada nas §§15–16; resta decidir a UI/modelo interno — decisão de produto, não técnica.

## 14. Origem oficial do formato: GCS (confirmado)

Com as referências fornecidas pelo dono dos dados, a pergunta aberta do §13 foi resolvida:

- **Ferramenta geradora:** [GCS — GURPS Character Sheet](https://github.com/richardwilkes/gcs), editor open-source em Go para fichas de GURPS 4ª edição, mantido por **Richard A. Wilkes** (~3,3 mil commits; atividade intensa até novembro/2026); licença MPL-2.0.
- **Terminologia:** no GCS, **"template"** é o pacote reaproveitável de construção (raça, meta-característica etc.) — exatamente o `"type": "template"` da raiz; o termo aparece também em issues antigas do projeto (ex.: ".GCT templates", #351, 2021). Internamente o código usa códigos próprios por tipo (`kinds.Template = 'B'`, trait `t`, skill `s`, armas `w`/`W`…), que NÃO aparecem nos `.gct` — são detalhe de implementação do app.
- **Cabeçalho de arquivo (formato atual):** todo arquivo novo de dados começa com `"file_type"` (string) e `"version"` (número) — implementado em `model/jio/version.go`. Arquivos antigos **sem** cabeçalho continuam legíveis: quando falta o tipo, valida-se só a versão; os campos são lidos onde estiverem no topo; a leitura remove BOM UTF-8 se presente.
- **Janela de versões:** `MinimumDataVersion = 2`, `CurrentDataVersion = 5`. Corpus analisado: **v2 sem cabeçalho** (legível hoje, na borda inferior da janela); saves contemporâneos: **v5 com cabeçalho**.
- **Escrita verificada no corpus:** JSON indentado com TAB, ordenação determinística e terminando em newline POSIX (`\n`) — 23/23 conferidos; nenhum BOM. Idêntico ao comportamento de gravação do GCS.
- **Ecossistema em movimento:** PRs de setembro–novembro/2026 mexeram justamente em containers de template, pré-requisitos/escolhas e sincronização com biblioteca (#1153, #1154, #1156, #1226) — a área que nos interessa está ativa; manter tolerância e fixtures (R2/R9/R13/R15).
- **Leitura completada em 27/11:** todo o guia relevante do repo foi consultado — síntese aplicada nas **§§15–§16**. Obs.: a página *Export Templates* trata da exportação de fichas (texto/HTML), não dos arquivos `.gct`.

---

## 15. Guia oficial do GCS — leitura aplicada ao importador

Síntese das páginas do userguide embutido no repo (`userguide/content/`), com cada conceito conferido contra os 23 arquivos. Fontes lidas: *Character Templates*, *Containers*, *Substitutions*, *Trait Modifiers*, *Traits*, *Skills*, *Melee and Ranged Weapons*, *Prerequisites*, *Features*, *Defaults*.

### Templates e fluxo de aplicação
- Um template é uma coleção reaproveitável (raças, profissões, kits) de traits/skills/spells/equipment/notes. Bloco do editor: Name, Target Points (min/max/exato), Page Reference/Highlight, Body Type (“Set to”) e Notes.
- Ao aplicar, o GCS pergunta nesta ordem: **choices → modifiers → substitutions → ancestralidade** — tudo dentro de uma única ação desfazível. Cancelar qualquer pergunta deixa a ficha intacta.
- Para raças, a prática oficial recomendada é usar container tipo **Ancestry** (faz nome/altura/peso aleatórios seguirem a ancestralidade) — casa com o campo `ancestry: "Human"` dos nossos templates de raça.

### Placeholders `@…@` (página *Substitutions*) — esclarecido
- São **substitution placeholders** oficiais: `@Codigo@` (letras, dígitos e `_`). O app pede o valor ao adicionar/aplicar e substitui o código onde ele aparecer.
- Estado **«not set»** mantém `@Codigo@` visível e volta a perguntar depois; **«empty»** troca por nada; `@` literal escreve-se `\@`. Definições formais (**Nameables**, com opções) só passaram a ser salvas em v5.56 — antes, era sempre texto livre.
- Nos nossos arquivos há códigos prontos para exibição (`@Comum: Venenos, Enjoos, etc.@`, `@Habilidade@`, `@Nadadeiras/Mastros/Remos/Velas@`). Regra prática: **nunca corromper nem traduzir** — tratar como pendência opcional de preenchimento (R16).

### Estados ligado/desligado e Preconfigured — refino do R3
- Trait/modificador **desabilitado** continua presente, mas **não contribui pontos, features nem ataques**; o checkbox *Enabled* controla isso.
- **Preconfigured** (só em templates/bibliotecas): escolhas/substituições já resolvidas — o app não pergunta ao aplicar.
- Conclusão para o nosso corpus: os 764 `"disabled": true` são opções **desmarcadas na origem** → entrar como variantes desligadas, fora dos totais, e reportá-las (R17).

### Features oficiais × subtipos do `.gct` (correspondência observada)
| Conceito no app (dropdown Features) | Tipo no JSON analisado |
|---|---|
| Gives an attribute modifier | `attribute_bonus` |
| Gives a skill level/point modifier | `skill_bonus` |
| Gives a spell level modifier | `spell_bonus` (bate também “colleges” ↔ `match:"all_colleges"`) |
| Gives a reaction modifier | `reaction_bonus` (+ situação) |
| Gives a DR bonus | `dr_bonus` (+ localização) |
| Reduces the cost of | `cost_reduction` |
| Weapon modifiers (dano/acerto/etc.) | `weapon_bonus` / objetos de dano |

Campos comuns oficiais: *Amount* (com *per level / per die / as %*), seletores de alvo e chips especiais — todos presentes nos nossos dados.

### Pré-requisitos — semântica confirmada
- Grupos combinadores: **All of / Any of / None of / Not all of**; tipos de requisito: trait, atributo, skill, spell, equipamento equipado/carregado, quantidade/peso contidos e condição de Tech Level.
- Comparações de nome: *is, is not, contains, starts with, ends with*; números: *is at least / is at most*. Nomes precisam bater **exatamente** (a comparação ignora maiúsculas/minúsculas) — vale também para defaults. Nosso `prereq_list{all:true}` + `advantage_prereq{has:false, name:{compare:...}}` converte direto (§9).

### Skills, defaults e armas
- Difficulty = atributo + letra (E/A/H/VH/W); técnicas usam só A/H e “Defaults To”.
- **Defaults**: fonte ∈ {10, atributo, Parry, Block, Skill, Spell} + modificador (+ condição de TL opcional); com vários defaults, vale o **melhor resultado**; *Swap Defaults* troca lugares. Nossos `defaults[]` têm exatamente esse desenho.
- Ataques vivem nas tabelas *Melee/Ranged Attack Usage* do item; ataques concedidos por modificador só aparecem **enquanto ele está habilitado**; todo ataque precisa de ≥1 default. Colunas canônicas batem com nossos objetos `melee_weapon`/`ranged_weapon` (§8).

### Descarte de nomenclatura
- A página *Export Templates* trata de **exportação de fichas** (texto/HTML/wiki via Go templates) e NÃO tem relação com a gravação dos `.gct` — registrar para evitar confusão futura.

---

## 16. Legado → atual: o que o próprio código do GCS revela (`template.go`)

Evidência direta de `model/gurps/template.go`, útil para a normalização do importador:

- **Save atual:** começa com o cabeçalho (`file_type`,`version`) e usa campos novos no topo: `id`, `name`, `reference`, `reference_highlight`, `local_notes`, `target_points`, `traits`, `skills`, `spells`, `equipment`, `notes`, `body_type`.
- **Compatibilidade oficial de leitura:** o código trata a chave antiga `advantages` como sinônimo de `traits` (aliás interno explícito: `OldTraits []*Trait \`json:"advantages"\`` → copiado para `Traits` quando a nova chave está ausente). Ou seja, o nosso lote v2 é reconhecido pelo app moderno e há migração automática na direção `advantages → traits`.
- **Limpeza na carga de template:** estudo, descrição de usuário e flags de desabilitado de *skills/spells/equipment* são removidos (só fazem sentido em ficha); containers de choice são normalizados; UUID inválido é regenerado. Flags em traits/modificadores sobrevivem — confirmando que o `disabled` do corpus é significativo (R17).
- **Carga via** `LoadVersionedFile(..., TemplateDataKind)` — mesma janela de versões do §14. Item em aberto de baixa prioridade: confirmar o valor exato da constante `TemplateDataKind` (o importador já tolera cabeçalho ausente).

### Tabela de migração (base da normalização proposta no R19)

| Formato legado (nosso corpus) | Formato atual | Nota |
|---|---|---|
| raiz `{type, version, id, advantages}` | raiz com header + `id, name, reference, …, traits` | nome/referência sobem para o topo |
| `advantages[0]` (container genérico) | `traits[]` (Trait com children/container) | alias gerenciado pelo próprio app |
| `calc.points` | `calc.points` (+ `target_points` novo) | pontos atuais ≠ pontos-alvo do template |
| skills internas | `skills[]` no topo | mesmo esquema de defaults/features |
| — | `equipment[]`, `notes[]`, `body_type` | campos possíveis no futuro |

---

## 17. Amostras adicionais recebidas (27/11 tarde) — três novos esquemas

Além dos 23 `.gct` originais, chegaram seis arquivos que cobrem outros pontos do ecossistema GCS: quatro saves de ficha (`.gcs`), uma transcrição `.gcs.txt` e um export `_gurps.json`. Todos são texto legível; **nenhum** tem cabeçalho `file_type`. Cada afirmação abaixo foi conferida por parse/scan dos arquivos reais.

### Esquema A — saves de ficha `.gcs` (dados versão 5)
Arquivos: *Little Mouse*, *PC – Kadda La*, *Twig-Eater*, *Wooly Rhino*.

- Raiz anônima (sem `type`): `{version:5, id, created_date, modified_date, total_points, attributes[], calc{}, profile{}, settings{}, traits[], skills[], equipment[], notes?[]}`. Sem campo de tipo — reconhecimento só por estrutura.
- **IDs**: novo padrão "TID" curto (18–20 caracteres alfanuméricos, ex. `AWejx2XDagAfpUpTm`), **não UUID**; convivem com chaves fixas tipo `neck`, `basic_move`. A deduplicação precisa aceitar os dois formatos (R20 ampliado).
- **Proveniência**: itens trazem `source:{library:"richardwilkes/gcs_master_library", path, id}`, `tags[]` (ex. `"Everyman"`) e campos novos: `can_level`, `children`, `cr_adj`, `local_notes`, `reference_highlight`, `replacements`.
- **Skills modernas**: `difficulty` nos moldes `dx/e`, `iq/a`; `defaults[]` com `name` podendo ser **string OU** `{compare:"is", qualifier:"…"}`; campos calculados `defaulted_from{level, adjusted_level, points}` e `calc{level, rsl}`.
- **Armas evoluídas**: têm `id` próprio, `sv` e `strength`; `damage{type, st, base}` agora com códigos curtos EN (`cr`, `cut`, `imp`; modos `thr`/`sw`) e `base` como `"-1"`/`"2d+1"`; `calc` pré-resolvido (`"damage":"1d-4 cr"`); `defaults[]` apontam habilidades pelo nome estruturado.
- **Subtipos novos**: `conditional_modifier` (feature com `situation` textual), `skill_prereq`, `trait_prereq`, `script_prereq`; `disabled:true` aparece nas fichas reais (5 a 50 por arquivo).
- `settings` guarda UI: `layout` com blocos `row/column/block`, `body_type{name, roll, locations}`, `damage_progression:"basic_set"` — fora do escopo funcional, mas preserváveis como blob.

### Esquema B — `.gcs.txt` = export JSON "character" (versão 2)
Arquivo: *Homem-Zebra-PT.gcs.txt* (apesar do sufixo `.txt`, é JSON indentado com tab).

- Raiz tipada: `{type:"character", version:2, id:<UUID>, attributes[], advantages[], skills[], equipment[], profile, settings, calc}`.
- **Valores prontos**: atributos como `{attr_id:"st", adj:3, calc:{value:13, points:30}}`; bloco `calc` pré-calculado (`swing:"2d-1"`, `thrust:"1d"`, arrays de `move`/`dodge`).
- Vantagens em PT com campos novos (`cr_adj:"action_penalty"`), features incluindo `conditional_modifier`, pré-requisitos **aninhados** (`prereq_list` dentro de `prereq_list`) e `skill_prereq` com especialização estruturada (`specialization:{compare:"is", qualifier:"Aplicada"}`).
- Exemplo de arma com `calc.level`=13 e `calc.damage`="1d cont" — mesma dualidade objeto/string do §8, agora com nomes PT ("Briga", "Boxe").
- 54 modificadores com `cost_type:"percentage"` — interpretar no Singular fica como decisão de produto (§13).

### Esquema C — `_gurps.json` (formato externo, não-GCS)
Arquivo: *ALDRIC DE BOSSONIA_gurps (1) (1).json* (1,8 MB).

- Estrutura própria: `{v:2, charName, ex{hp, fp, will, per, speed, move, super_*…}, pts, social[], reactionChecks{}, sHTML, portrait(base64), fgMembership, mainTab:"pericias", sheetMode:"criacao"}`.
- Rótulos em PT ("combate", "pericias"), HTML embutido e retrato em base64; formato próprio do ecossistema — **não** é GCS nativo (origem identificada na **§19**). Ação imediata: guardar cru; suporte entra como candidata pós-`.gct`/`.gcs`.

### Consequências para o importador (adendo às recomendações)
- Passam a existir **quatro famílias de envelope** a reconhecer por estrutura: `.gct` legado (container único `advantages`), `.gct`/dados atuais com header, `.gcs` v5 (ficha) e `.gcs.txt` ("character" v2). Extensões continuam irrelevantes.
- Enums de dano migraram de rótulo PT (`corte/perf/cont/qmd`) para códigos curtos (`cr/cut/imp` + `st: thr/sw` + `base`); equivalências definitivas na **§18** (mantenha fallback cru para valores desconhecidos).
- `defaults[]` e referências de skill aceitam as duas formas (string / `{compare, qualifier}`) em qualquer idioma (R23).
- Aceitar UUID, TID curto e ausência de id (chave derivada de conteúdo como último recurso); nunca colidir itens por "mesmo nome" (R1/R20).
- Preservar `source{library, path, id}` e `tags[]` (R24) — é a ponte para sincronização futura com bibliotecas.

**Resolvido em 27/11:** (a) origem do formato C — é do **Singular**, o programa irmão do Plural (**§19**); (b) mapeamento de dano antigo ↔ atual — fechado na **§18** — esclarecido no mesmo dia: as intensidades vêm de variações de bala/munição ou da vantagem **Ataque Inato**; ver §18. **Resolvido também em 27/11:** (c) fase 2 implantada — `.gct` e `.gcs/.gcs.txt` são convertidos pelo mesmo motor (selftest em duas suítes); o formato externo (`_gurps.json`) permanece fora do escopo.

## 18. Glossário PT ↔ EN do acervo (confirmado pelo dono dos dados)

Passado por escrito pelo responsável do material em 27/11 — fonte autoritativa para normalizar enums, traduções e migrações. Substitui as hipóteses anteriores (§7, §17, R22).

**Tipos de dano e golpes:**

| PT (acervo) | EN (código) | Observação |
|---|---|---|
| corte | cutting (`cut`) | — |
| perfurante (`pa`) | piercing (`pi`) | intensidades: pouco, muito, extremamente — em regra ligadas a variedades de bala (munição) ou à vantagem **Ataque Inato** |
| perfuração (`perf`) | impaling (`imp`) | — |
| fadiga (`fad`) | fatigue (`fat`) | — |
| queimadura (`qmd`) | burn | explica o `qmd` dos ataques de fogo (baforada, corpo de fogo) |
| contusão (`cont`) | crushing (`cr`) | — |
| golpe em balanço (`GeB`) | swing (`sw`) | modo de ST (`st`) |
| golpe de ponta (`GdP`) | thrust (`thr`) | modo de ST (`st`) |

**Termos gerais:**

| EN | PT (acervo) |
|---|---|
| health | vitalidade |
| hit points (`HP`) | pontos de vida (`PV`) |
| fatigue points (`FP`) | pontos de fadiga (`PF`) |
| damage resistance (`DR`) | resistência de dano (`RD`) |
| `DB` | `BD` |
| fine quality | qualidade superior |
| very fine | altíssima qualidade |
| fright check | verificação de pânico (alias para o “teste de pavor” visto em §7) |
| will | vontade (`vont`) |
| quirk | peculiaridade |
| perk | qualidade |
| enhancement | ampliação |

Aplicação: usar nas camadas de normalização/exibição; quando vier termo fora da tabela, preservar cru e sinalizar (nunca sobrescrever).

> **Regra de contexto:** aparições de “perfurante” com intensidade costumam indicar **variedade de bala/munição** ou origem na vantagem **Ataque Inato** — usar como pista de classificação, sem criar tipo novo.

## 19. Ecossistema: Singular (o “programa irmão do Plural”)

- Confirmado pelo dono dos dados: o formato C (§17, arquivo *ALDRIC*) vem do **Singular** — descrito como “programa irmão do Plural” — que é o aplicativo-web deste ecossistema (kit de fichas e cálculos GURPS em PT-BR).
- Referências oficiais (informadas pelo usuário): repositório [github.com/BaHalus/Singular](https://github.com/BaHalus/Singular) e demonstração ao vivo [bahalus.github.io/Singular](https://bahalus.github.io/Singular/).
- Conferido na demo/repo (27/11): o Singular convive lado a lado com o GCS — importa bibliotecas RAW GCS (`.gct`, `.skl`, `.adq`, `.eqp`, `.spl`, `.eqm`, `.adm` ou JSON/TXT), oferece **“Baixar GCS”** e mantém backup/compartilhamento próprios em JSON; versões públicas na faixa 0.11.x.
- Implicação para o importador: o `_gurps.json` deixa de ser “formato de terceiro desconhecido” e passa a ser **formato amigo do ecossistema** — candidato natural a suporte depois dos `.gct`/`.gcs` (decisão de escopo para a v0.7.2+).

## Apêndice A — Catálogo dos 23 arquivos

| Categoria | Nome | Ref. | Pontos | Itens | Skills na raiz |
|---|---|---|---:|---:|---:|
| Metacaracterística | Animal Doméstico | B263 | −30 | 4 | 0 |
| Metacaracterística | Animal Selvagem | B263 | −30 | 4 | 0 |
| Metacaracterística | Autômato | B263 | −85 | 5 | 0 |
| Metacaracterística | Corpo de Ar | B263 | 16 | 8 | 0 |
| Metacaracterística | Corpo de Fogo | B263 | 7 | 8 | 0 |
| Metacaracterística | Corpo de Gelo | B263 | 87 | 12 | 0 |
| Metacaracterística | Corpo de Metal | B263 | 175 | 7 | 0 |
| Metacaracterística | Corpo de Pedra | B263 | 140 | 8 | 0 |
| Metacaracterística | Corpo de Terra | B263 | 175 | 8 | 0 |
| Metacaracterística | Corpo de Água | B263 | 170 | 9 | 0 |
| Metacaracterística | Entidade Astral | B262 | 171 | 7 | 0 |
| Metacaracterística | Espírito | B262 | 261 | 7 | 0 |
| Metacaracterística | Ictioide | B263 | −50 | 2 | 0 |
| Metacaracterística | Inteligência Artificial | B263 | 32 | 6 | 0 |
| Metacaracterística | Máquina | B262 | 25 | 6 | 0 |
| Metacaracterística | Quadrúpede | B263 | −35 | 3 | 0 |
| Metacaracterística | Vermiforme | B263 | −35 | 3 | 0 |
| Metacaracterística | Veículo Terrestre | B263 | −100 | 4 | 0 |
| Raça | Anão | B261 | 35 | 5 | 0 |
| Raça | Dragão (Básico) | B261 | 260 | 19 | 2 |
| Raça | Elfo | B316 | 69 | 8 | 1 |
| Raça | Felinoide | B261 | 35 | 14 | 0 |
| Raça | Vampiro | B262 | 150 | 24 | 0 |

*Colunas "Itens/Skills" são contagens dos filhos diretos no container e das skills de raiz; valores negativos indicam meta-características de baixo custo.*
