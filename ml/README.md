# PavimentAI – pasta `ml`

Teste do modelo de detecção de buracos (YOLO11n, classe única `buraco`) em fotos e vídeos reais.

## Conteúdo

- `weights/best.pt` – modelo treinado (`oitavotreino`)
- `testar_modelo.py` – roda o modelo em vídeo, imagem ou pasta
- `requirements.txt` – dependências

## Instalação (no seu computador)

```bash
python -m venv venv
# Windows: venv\Scripts\activate   |   Linux/Mac: source venv/bin/activate
pip install -r requirements.txt
```

## Uso

```bash
python testar_modelo.py minha_rua.mp4
python testar_modelo.py pasta_com_fotos/
python testar_modelo.py minha_rua.mp4 --conf 0.4          # menos falsos alarmes
python testar_modelo.py minha_rua.mp4 --salvar-frames 10  # salva frames para revisão
```

Os resultados ficam em `resultados/<nome_do_arquivo>/`:
`video_anotado.mp4`, `deteccoes.csv`, `resumo.txt` e, se pedir, `frames_deteccao/`.

## Como gravar o vídeo de teste

Este é o teste que mais importa: ele mostra se o modelo funciona fora do dataset.

- Prenda o celular **na posição em que a câmera do Raspberry ficará** (painel ou para-brisa, olhando para a rua), na horizontal, 1080p, 30 fps.
- Grave ruas de Mauá com buracos de verdade e também ruas sem buraco.
- Varie as condições: sol forte, sombra de árvores, fim de tarde, rua molhada, asfalto novo e velho.
- Inclua de propósito os casos que costumam enganar o modelo: tampa de bueiro, remendo de asfalto, lombada, rachadura, mancha e sombra.
- Segurança: quem dirige não grava. Peça a outra pessoa para conferir o celular e respeite o limite de velocidade. Prefira velocidade baixa (20 a 30 km/h).
- Cuidado com privacidade (LGPD): vídeos mostram rostos e placas. Não publique esses vídeos sem borrar essas áreas.

## Como avaliar de verdade (conte à mão)

O número do tracker é só uma aproximação. Assista ao `video_anotado.mp4` e preencha uma tabela como esta para cada trecho:

| Trecho | Buracos reais | Acertos (detectados) | Perdidos | Falsos alarmes | Distância (km) |
|---|---|---|---|---|---|
| Rua A | | | | | |
| Rua B | | | | | |

Depois calcule:
- **Recall do trecho** = acertos ÷ buracos reais
- **Precisão do trecho** = acertos ÷ (acertos + falsos alarmes)
- **Falsos alarmes por km**

Anote também quais objetos viraram falso alarme (bueiro, sombra etc.). Isso diz o que precisa entrar no retreino.

## Como decidir o que fazer

- Muitos falsos alarmes: rode de novo com `--conf 0.35`, `0.45` e `0.55` e compare os números de cada um.
- Muitos buracos perdidos: a câmera pode estar mal posicionada, ou o modelo não conhece essas condições. Junte os frames problemáticos para o retreino.
- Resultado bom no vídeo real: siga para a API e o hardware.
- Resultado ruim: colete imagens suas, rotule e faça fine-tuning a partir do `best.pt`.

## Observações

- O tempo em ms por frame é do **seu computador**, não do Raspberry. A velocidade no Raspberry só se sabe testando nele.
- As métricas do treino (mAP50 0,885 na validação e 0,849 no teste) vêm do dataset original, não de vídeo de rua real.

## Conferir se o dataset tem imagens repetidas (vazamento)

Se a mesma foto (ou uma versão espelhada/recomprimida) estiver no treino e no teste, as métricas ficam infladas.
Rode no computador onde está o `dataset_unificado` (precisa de `pip install pillow numpy`, que já vêm com o ultralytics):

```bash
python checar_vazamento.py caminho/para/dataset_unificado
```

Ele imprime quantas imagens de validação e de teste têm uma parecida no treino e salva os pares em `vazamento.csv`.
Perto de 0% é ótimo; acima de uns 5 a 10% as métricas do teste estão otimistas.

## Planilha do teste de campo

Use `planilha_avaliacao_campo.csv` (abre no Excel) para anotar cada trecho dos vídeos. Depois calcule:
recall = acertos ÷ buracos reais; precisão = acertos ÷ (acertos + falsos alarmes); falsos alarmes por km.

## Pasta `treino_oitavotreino`

Cópia das métricas, curvas, matrizes de confusão e do notebook do treino, para documentação.
Atenção: `confusion_matrix.png` foi gerada com confiança mínima 0,001 e mostra muitos falsos positivos de propósito;
para apresentar, use a matriz que você gerou no notebook com `conf=0.25`.
