# AccessFlow · C.H.I.C.O. — Robô monitor de iluminação acessível 🤖💡

> **Global Solution 2026.2 · CitizenTech** — FIAP Engenharia de Software (4ES)
> Disciplina: **Project-Based Maker Lab** — Componente *Físico* do MVP AccessFlow
---

## 👥 Integrantes

| Nome | RM |
|------|----|
| Juliana Villalpando Maita | 99224 |
| João Victor Dos Santos Morais | 550453 |
| Luana Cabezaolias | 99320 |
| Pedro Henrique Pontes Farath | 98608 |
| Lucca Vilaça Okubo | 551538 |

---

## 🧭 O problema (CitizenTech)

O **AccessFlow** monitora barreiras em **passagens acessíveis de clínicas e unidades de saúde**.
Uma barreira pouco lembrada é a **iluminação insuficiente**: corredor escuro, lâmpada queimada ou
penumbra no fim da tarde aumentam o risco de **quedas de idosos** e dificultam a orientação de
**pessoas com baixa visão**. Normalmente ninguém percebe até alguém reclamar ou se machucar.

## 💡 A solução

Evoluímos o robô **Chico** (assistente de voz feito em MDF com Arduino) com um **sensor de
luminosidade (LDR)**. Agora ele:

1. **Mede a luz do ambiente continuamente**, sem precisar de comando;
2. **Classifica** a iluminação em *adequada*, *baixa* ou *crítica* em relação à luz de referência do local;
3. **Reage fisicamente**: olhos (LEDs) piscam e a cabeça (servo) se move conforme o nível;
4. **Avisa por voz** com uma mensagem **gerada por IA (Gemini)** que considera nível, horário e quem é afetado;
5. **Registra cada ocorrência** (início, fim, pior nível, duração) e gera **relatório falado para a manutenção**;
6. **Detecta falhas** (fio solto, Arduino desconectado) e continua funcionando em **modo autônomo** sem o PC.

---

## 🏗️ Arquitetura

```
 ┌──────────── Arduino Uno ────────────┐        USB serial         ┌──────────────── PC (Python) ────────────────┐
 │ LDR (A0) ──► leitura média 5x       │  "L:<0-1023>" a cada 200ms │ sensor_luz.py  (thread)                       │
 │                                     │ ─────────────────────────► │  média móvel → % da referência                │
 │ Servo (9)  ◄── comportamento        │                            │  classificação c/ histerese + persistência 3s │
 │ LEDs (8,12)  ◄─ por modo            │ ◄───────────────────────── │  detecção de falha / reconexão automática     │
 │                                     │  "M:N|A|C|F" a cada 1s     │  CSV: leituras + ocorrências                  │
 │ Sem PC por 5s → MODO AUTÔNOMO       │      (heartbeat)           │        │ evento de mudança                    │
 │ (classifica sozinho)                │                            │        ▼                                      │
 └─────────────────────────────────────┘                            │ alerta_luz.py → Gemini (fallback offline)    │
                                                                    │        ▼                                      │
                                                                    │ chico.py → voz (edge-tts) + comandos de voz   │
                                                                    └───────────────────────────────────────────────┘
```

| Nível | Critério (% da luz de referência) | Olhos (LEDs) | Cabeça (servo) | Ação do Chico |
|---|---|---|---|---|
| ADEQUADA | ≥ 60% | acesos fixos | centro (90°) | avisa quando a luz **volta** ao normal |
| BAIXA | 30% a 60% | piscam devagar | inclinada (65°) | alerta de atenção gerado pela IA |
| CRITICA | < 30% | piscam rápido | varre 45°–135° ("procurando") | alerta crítico + registra para manutenção |
| FALHA | leitura travada em 0 ou 1023 | alternam E/D | centro | avisa para checar a fiação |

**Decisões de projeto para leituras confiáveis:**
- **Média de 5 amostras** no Arduino + **média móvel** no Python → reduz ruído;
- **Histerese de 5%** → não fica alternando quando a luz está na fronteira;
- **Persistência de 3 s** → uma sombra passando na frente do sensor **não** gera alarme falso;
- **Calibração por voz** (`Chico, calibrar luz`) → a luz atual vira os 100% do local (cada corredor é diferente).

---

## 🔌 Montagem (componentes)

| Componente | Qtde | Ligação |
|---|---|---|
| Arduino Uno | 1 | USB no PC |
| **LDR (fotoresistor)** | 1 | 5V → LDR → **A0** → resistor 10kΩ → GND |
| Resistor 10kΩ | 1 | divisor de tensão do LDR |
| Micro servo SG90 | 1 | sinal **pino 9**, VCC 5V, GND |
| LED (olhos) | 2 | **pinos 8 e 12** → resistor 220Ω → GND |
| Resistor 220Ω | 2 | LEDs |
| Protoboard + jumpers | — | — |

> Usando um **módulo LDR** (plaquinha de 3 pinos)? Ligue o pino `AO` no A0 e troque
> `LDR_INVERTIDO = true` no `.ino` (nesses módulos, mais luz = valor menor).

**Gravar o firmware:** abra `arduino/chico_ldr/chico_ldr.ino` na Arduino IDE → placa *Arduino Uno* → Upload.
Pode testar abrindo o Monitor Serial em **115200** (deve aparecer `S:PRONTO` e linhas `L:...`); depois **feche** o Monitor Serial.

---

## 🎤 Comandos de voz do sensor

| Comando | O que faz |
|---|---|
| *(nenhum)* | O monitoramento e os alertas são **automáticos** |
| `Chico, como está a iluminação?` | Fala o nível e a % atual |
| `Chico, calibrar luz` | Define a luz atual como referência (100%) |
| `Chico, relatório de iluminação` | IA resume as ocorrências para a manutenção |
| `Chico, simular escuro / penumbra / claro / falha` | Só no modo `SENSOR_PORTA=SIMULADO` (testes sem Arduino) |

Arquivos gerados em `data/`:
- `leituras_luz.csv` — leitura a cada 2 s (timestamp, local, bruto, %, nível)
- `ocorrencias_luz.csv` — cada período de pouca luz/falha + mensagem gerada pela IA
- `calibracao_luz.txt` — referência calibrada

---

## 🧪 Testes e cenários demonstrados

| Cenário | Como reproduzir | Resultado esperado |
|---|---|---|
| Luz normal | ambiente iluminado | olhos fixos, sem alerta |
| Penumbra | cobrir parcialmente o LDR / apagar uma luz | após 3 s: olhos piscando devagar, alerta de atenção |
| Escuro | cobrir o LDR com a mão | após 3 s: cabeça varrendo, alerta crítico |
| Sombra rápida | passar a mão rápido na frente | **nenhum** alerta (persistência) |
| Luz volta | descobrir o LDR | "iluminação voltou ao normal", ocorrência gravada no CSV |
| Fio do LDR solto | desconectar o fio do A0 | estado FALHA, olhos alternando, aviso por voz |
| PC desligado / script fechado | fechar o Python | em 5 s o Arduino entra em **modo autônomo** e segue sinalizando |
| Cabo USB desconectado | tirar o cabo | Chico avisa e reconecta sozinho ao voltar |

Testar só o sensor (sem voz):
```bash
python sensor_luz.py                      # com Arduino
SENSOR_PORTA=SIMULADO python sensor_luz.py  # sem Arduino
```

---

## 🗂️ Arquivos novos desta entrega

```
arduino/chico_ldr/chico_ldr.ino  # firmware: LDR, servo, LEDs, modo autônomo
sensor_luz.py                    # leitura serial, classificação, CSV, simulação
alerta_luz.py                    # IA (Gemini) para alertas e relatório + fallback offline
chico.py                         # integra o sensor (thread + alertas automáticos + comandos)
roteador.py                      # novos intents: status_luz, calibrar_luz, relatorio_luz, simular_luz
ia_generativa.py                 # método gerar() com system prompt próprio
```

---

### Comandos herdados do Chico (CP4)

| # | Comando | Descrição |
|---|---------|-----------|
| 1 | `Chico` | Ativa a assistente para receber comandos |
| 2 | `Chico cadastrar evento na agenda` | Salva um evento em `agenda.txt` |
| 3 | `Chico ler agenda` | Lê todos os eventos cadastrados |
| 4 | `Chico que horas são?` | Informa a hora atual |
| 5 | `Chico que dia é hoje?` | Informa o dia da semana e data |
| 6 | `Chico calcular 10 mais 5` | Operações básicas (+, -, ×, ÷) |
| 7a | `Chico cadastrar rosto` | Tira fotos e treina o modelo com o seu nome |
| 7b | `Chico reconhecer face` / `quem sou eu?` | Abre a webcam e identifica a pessoa |
| 8 | `Chico limpar agenda` | Apaga todos os eventos da agenda |
| 9 | `Chico o que é machine learning?` | Consulta o Google Gemini (IA generativa) |
| 10a | `Chico previsão do tempo em São Paulo` | Clima em tempo real (Open-Meteo) |
| 10b | `Chico qual o valor do dólar` | Cotação USD-BRL em tempo real |
| 10c | `Chico quanto vale um bitcoin` | Cotação BTC-BRL em tempo real |
| 10d | `Chico tocar Shape of You no Spotify` | Toca a faixa no app do Spotify |
| 10d+ | `Chico pausar` / `próxima` / `anterior` / `continuar` | Controla a reprodução |
| 10e | `Chico pesquisar Python no Google` | Abre busca no Google |
| 10f | `Chico aumenta o volume` / `diminui` / `mutar` | Controle de volume (Windows pycaw / Mac osascript) |
| 10g | `Chico tira um print da tela` | Screenshot cross-platform (mss) |
| 10h | `Chico abre o YouTube e toca um vídeo sobre Python` | Abre YouTube pesquisando o tema |
| 10i | `Chico abre o portal da faculdade` | Abre o portal FIAP |

> Itens 10f–10i são extras do item 10 do PDF (cross-platform Windows/Mac com retry automático).

> **Regra obrigatória:** qualquer comando só é processado após o usuário dizer "Chico".

---

## ⚙️ Instalação

### 1. Clone o repositório
```bash
git clone https://github.com/SEU-USUARIO/accessflow-chico-makerlab.git
cd accessflow-chico-makerlab
```

### 2. Crie e ative um ambiente virtual (Python 3.11)
```bash
py -3.11 -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/Mac
source .venv/bin/activate
```

### 3. Instale as dependências
```bash
pip install -r requirements.txt
```

> **Windows — PyAudio:**
> Se der erro ao instalar o PyAudio:
> ```bash
> pip install pipwin
> pipwin install pyaudio
> ```

### 4. Configure a chave do Gemini

1. Acesse [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Crie uma chave gratuita
3. Copie `.env.example` para `.env` e insira a chave:
```env
GEMINI_API_KEY=sua_chave_aqui
```

### 5. Configure o Spotify (playback de verdade)

A API do Spotify **não entrega o áudio** para o Python. O Chico busca a faixa e manda o **app desktop do Spotify** tocar.

1. Instale o [Spotify](https://www.spotify.com/download/) no computador e faça login (conta **Premium** reproduz qualquer faixa; Free tem as limitações do próprio Spotify).
2. Crie um app em [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard).
3. Copie Client ID e Client Secret para o `.env`:
```env
SPOTIFY_CLIENT_ID=seu_client_id
SPOTIFY_CLIENT_SECRET=seu_client_secret
```

Sem essas chaves, o Chico só abre a busca no navegador (comportamento antigo).

### 6. Configure o sensor (AccessFlow)
No `.env`:
```env
# Porta do Arduino. Deixe vazio para detectar sozinho (COM3, /dev/ttyUSB0, /dev/cu.usbmodem...)
# Use SIMULADO para testar sem o Arduino
SENSOR_PORTA=
SENSOR_LOCAL=corredor de acesso da clínica
```
Antes, grave o firmware no Arduino (veja **Montagem** acima) e **feche o Monitor Serial da IDE** (senão a porta fica ocupada).

### 7. Execute
```bash
python main.py
```

---

## 🎤 Como usar

Ao iniciar, o sistema aguarda você dizer (ou digitar) **"Chico"** seguido do comando:

```
⌨️  Digite o comando (Enter para usar voz): chico que horas são
🤖 Chico: São 14 horas e 30 minutos.
```

Ou apenas pressione Enter para usar o microfone:
```
🎙️  Aguardando ativação ('Chico')...
   ✅ Reconhecido: 'chico cadastrar evento na agenda'
🤖 Chico: Ok! Qual evento devo cadastrar?
```

---

## 🧠 Reconhecimento Facial

O modelo **não vem pronto**: primeiro cadastre o rosto, depois reconheça.

1. `Chico cadastrar rosto` → diga o nome → olhe para a câmera (60 fotos) → o modelo é treinado sozinho
2. `Chico quem sou eu?` ou `Chico reconhecer face` → a câmera identifica a pessoa
3. Na janela da câmera, pressione **q** para encerrar (ou aguarde: fecha sozinha ao confirmar a pessoa)

No macOS, autorize o Terminal/Cursor em **Ajustes → Privacidade e Segurança → Câmera**.

**Melhorias no reconhecimento facial:**
- Alinhamento do rosto pelos olhos + normalização de contraste (CLAHE), tornando o modelo mais tolerante a inclinação de cabeça e luz irregular.
- Filtros de qualidade na captura: só salva fotos nítidas, bem iluminadas e com o rosto perto o bastante da câmera — mostra na tela o que ajustar.
- Dicas de pose durante o cadastro (virar levemente a cabeça, sorrir) para variar o ângulo capturado.
- Recadastrar uma pessoa **adiciona** fotos novas em vez de sobrescrever as antigas.
- Treino com pequenas variações (rotação leve e brilho) de cada foto, para generalizar melhor com poucas fotos.
- Reconhecimento por votação em vários frames (não decide só pelo último frame antes de fechar a câmera) e fecha sozinho ao confirmar a pessoa.
- Correção do nome: frases como "meu nome é Pedro" agora viram a pasta `pedro`, não `meu_nome_e_pedro`.

> Se você já tinha rostos cadastrados antes dessas melhorias, vale apagar `data/rostos/`, `data/face_model.yml` e `data/face_nomes.txt` e cadastrar de novo — assim todas as fotos já ficam alinhadas e normalizadas do mesmo jeito.

Também dá para treinar sem a assistente:

```bash
python face.py cadastrar Maria
python face.py reconhecer
```

---

## 🧭 Roteamento por Embeddings

Comandos **não são** `if "palavra" in frase`. O `roteador.py` vetoriza a frase e compara (cosseno) com exemplos de cada intent.

- **Padrão:** TF-IDF offline (sklearn, instantâneo, sem internet) — já vem pronto.
- **Opcional:** embeddings reais do Gemini (`text-embedding-004`) — descomente o bloco em `roteador.py:_vetorizar` e use `Roteador(usar_gemini=True)` (precisa de `GEMINI_API_KEY`).

```bash
# Testa o roteador sem microfone
.venv\Scripts\python.exe roteador.py
# ou uma frase especifica
.venv\Scripts\python.exe -c "from roteador import Roteador; print(Roteador().explicar('aumenta o volume'))"
```

Isso pega variações tipo "marca um compromisso pra mim" → `cadastrar_agenda` ou "me diz o horário atual" → `hora` sem cadastrar cada sinônimo.

---

## 📦 Dependências Principais

| Biblioteca | Versão | Uso |
|-----------|--------|-----|
| SpeechRecognition | 3.10.4 | Reconhecimento de voz (Google STT) |
| pyttsx3 | 2.99 | Síntese de voz offline (fallback) |
| edge-tts | 7.2.3 | Voz neural pt-BR |
| pygame | 2.6.1 | Reprodução de áudio no Windows (sem abrir player) |
| PyAudio | 0.2.14 | Captura de áudio do microfone |
| google-genai | 1.2.0 | Google Gemini (IA generativa) |
| scikit-learn | 1.5.2 | Roteamento por embeddings (TF-IDF) |
| opencv-python | 4.10.0.84 | Reconhecimento facial (Haar) |
| opencv-contrib-python | 4.10.0.84 | LBPHFaceRecognizer |
| mss | 10.2.0 | Screenshot cross-platform |
| pycaw | 20251023 | Controle de volume no Windows |
| requests | 2.32.3 | APIs de clima e cotações |
| python-dotenv | 1.0.1 | Variáveis de ambiente |
| pyserial | 3.5 | Comunicação com o Arduino (sensor LDR) |

---
## 📄 Link Youtube
---
https://youtube.com/shorts/kJKFTZ26VtY?is=BVzZnjs5JVn6kAOy
## 📄 Licença

Projeto acadêmico — FIAP 2026.
