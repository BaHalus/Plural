# Patch v0.5.30 — Correção dos botões de perícia na comparação

## Problema

Na aba **Comparar**, na seção **📜 Perícias**, o botão de rolagem aparecia como código HTML em vez de botão.

A causa foi passar HTML pronto para uma função que aplica escape de caracteres. O `esc()` transformou `<button ...>` em texto visível.

## Correção

No trecho que monta as células da comparação, para a seção de perícias, usar o HTML do botão diretamente:

```js
// Antes
return its.length?its.map(x=>roll?skillCell(x):cellTxt(x)).join('<br>'):[]

// Depois
return its.length?its.map(x=>roll?skillCell(x):esc(x.value??'—')+(x.points!=null?' <small>['+esc(x.points)+' pts]</small>':'')+(x.detail?' <small>'+esc(x.detail)+'</small>':'')).join('<br>'):[]
```

E, para perícias, usar o botão sem escape:

```js
return its.length?its.map(x=>roll
  ? '<button data-skillroll="'+esc(x.value)+'" style="min-height:28px;padding:2px 8px">'+esc(x.value)+'</button>'+(x.points!=null?' <small>['+esc(x.points)+' pts]</small>':'')+(x.detail?' <small>'+esc(x.detail)+'</small>':'')
  : cellTxt(x)
).join('<br>'):[]
```

## Resultado esperado

- Na comparação, o NH da perícia volta a aparecer como botão.
- Toques no botão rolam 3d6 contra o NH.
- O pop-up mostra sucesso, fracasso, margem e crítico.
- A ficha continua com o botão de rolagem funcionando.
- As demais seções da comparação continuam escapando o conteúdo normalmente.
