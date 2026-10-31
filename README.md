# 🌐 URBIX
### Inteligência urbana para cidades mais acessíveis e conectadas.

> Uma plataforma de monitoramento e mapeamento urbano que integra inteligência artificial, geolocalização e participação cidadã para identificar problemas na infraestrutura das cidades.

---

## 🏙️ Sobre o projeto

O **URBIX** é uma solução tecnológica em desenvolvimento que busca transformar a maneira como problemas urbanos são identificados, registrados e visualizados.

A plataforma possui duas frentes principais:

- **Monitoramento automatizado:** utilização de câmeras instaladas em veículos de circulação cotidiana, como caminhões de coleta de resíduos, para identificar buracos nas vias por meio de visão computacional.
- **Mapeamento colaborativo:** permite que cidadãos registrem problemas de acessibilidade, como calçadas danificadas, ausência de rampas e obstáculos à circulação.

As ocorrências são organizadas geograficamente, formando uma base de dados que poderá auxiliar o planejamento e a gestão pública.

## ⚙️ Funcionalidades

- [x] Treinamento do modelo de detecção de buracos.
- [x] Avaliação experimental da inteligência artificial.
- [x] Desenvolvimento inicial da API.
- [ ] Sistema de autenticação e gerenciamento de usuários.
- [ ] Registro e gerenciamento de ocorrências.
- [ ] Mapeamento geográfico interativo.
- [ ] Denúncias cidadãs de problemas de acessibilidade.
- [ ] Integração com câmeras e GPS em veículos.
- [ ] Integração com Raspberry Pi.
- [ ] Testes em ambiente real.

## 🧠 Inteligência artificial

O projeto utiliza o modelo **YOLO11n**, treinado para identificar buracos em imagens de vias públicas.

**Resultados experimentais:**

| Métrica | Resultado |
|---|---:|
| Precision | 86,28% |
| Recall | 82,75% |
| mAP@50 | 89,08% |
| mAP@50-95 | 56,02% |

**Dataset:** 2.495 imagens e 8.917 anotações.

*Os resultados são experimentais e ainda precisam ser validados em condições reais de operação.*

## 🛠️ Tecnologias

| Área | Tecnologias |
|---|---|
| Inteligência artificial | Python, YOLO11n |
| Backend | Python, FastAPI |
| Banco de dados | PostgreSQL, PostGIS |
| Frontend | JavaScript, HTML, CSS |
| Mapas | Leaflet.js |
| Visualização | Chart.js |
| Hardware planejado | Raspberry Pi, câmera e GPS |

## 🗂️ Estrutura do projeto

```text
URBIX/
├── api/       # Backend e serviços
├── ml/        # Modelos e processamento de IA
├── web/       # Interface da plataforma
├── docs/      # Documentação técnica
└── README.md  # Apresentação do projeto
```

## 🌱 Impacto social

O URBIX busca contribuir para:

- **ODS 11:** Cidades e Comunidades Sustentáveis.
- **ODS 9:** Indústria, Inovação e Infraestrutura.
- **ODS 10:** Redução das Desigualdades.

## 👥 Equipe

Projeto desenvolvido por uma equipe de três estudantes, com orientação docente, no contexto de pesquisa e desenvolvimento tecnológico.

---

<p align="center">
  <strong>Tecnologia para compreender as cidades e melhorar a vida de quem vive nelas.</strong>
</p>

**Status:** Em desenvolvimento 🚧