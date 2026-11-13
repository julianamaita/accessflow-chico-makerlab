/*
 * C.H.I.C.O. + AccessFlow — Firmware do robô (Arduino Uno)
 * Global Solution 2026.2 · CitizenTech · Project-Based Maker Lab
 *
 * Função:
 *   - Lê o sensor de luminosidade (LDR) e envia a leitura ao PC pela serial.
 *   - Recebe do PC (Python/IA) o nível de iluminação classificado e reage:
 *       olhos (LEDs) e cabeça (servo) mudam de comportamento.
 *   - MODO AUTÔNOMO: se o PC parar de responder por 5 s, o próprio Arduino
 *     classifica a luz e continua sinalizando (tolerância a falha).
 *
 * Ligações (ajuste as constantes abaixo se os seus pinos forem outros):
 *   LDR ........ divisor de tensão: 5V -> LDR -> A0 -> resistor 10k -> GND
 *   Servo ...... sinal no pino 9, VCC no 5V, GND no GND
 *   LED olho E . pino 8  (com resistor ~220Ω) -> GND
 *   LED olho D . pino 12 (com resistor ~220Ω) -> GND
 *
 * Protocolo serial (115200 baud, uma mensagem por linha):
 *   Arduino -> PC : "L:<0-1023>"           leitura bruta do LDR (a cada 200 ms)
 *                   "S:PRONTO"             firmware iniciou
 *                   "S:AUTONOMO" / "S:CONECTADO"
 *   PC -> Arduino : "M:N" normal | "M:A" atenção | "M:C" crítico | "M:F" falha do sensor
 *                   (o PC reenvia o modo a cada 1 s; isso serve de "heartbeat")
 */

#include <Servo.h>

// ---------------- Pinos ----------------
const int PINO_LDR      = A0;
const int PINO_SERVO    = 9;
const int PINO_OLHO_ESQ = 8;
const int PINO_OLHO_DIR = 12;

// ---------------- Ajustes ----------------
// Se o seu LDR for um MÓDULO (placa com 3 pinos), normalmente mais luz = valor MENOR.
// Nesse caso troque para true.
const bool LDR_INVERTIDO = false;

// Limites usados só no MODO AUTÔNOMO (sem PC). Valores brutos 0-1023.
// Calibrados para LDR + resistor 1kΩ: escuro ~10, luz do ambiente ~55, lanterna ~600.
// Se trocar para resistor de 10kΩ, aumente (ex.: 350 e 150).
const int LIMITE_ATENCAO_LOCAL = 35;
const int LIMITE_CRITICO_LOCAL = 20;
const int LIMITE_FALHA_BAIXO   = 1;     // 0 travado = fio do LDR solto
const int JANELA_MEDIA_LOCAL   = 5;     // média móvel (~1 s) contra o ruído do servo/LEDs

const unsigned long INTERVALO_LEITURA_MS = 200;
const unsigned long TIMEOUT_PC_MS        = 5000;

// ---------------- Estado ----------------
Servo cabeca;
char modo = 'N';                 // N, A, C, F
bool autonomo = true;            // começa autônomo até o PC falar
unsigned long ultimoContatoPC = 0;
unsigned long ultimaLeitura   = 0;
unsigned long ultimoPisca     = 0;
unsigned long ultimoServo     = 0;
bool estadoPisca = false;
int anguloServo = 90;
int passoServo  = 5;
String buffer = "";
int historico[JANELA_MEDIA_LOCAL];
int idxHist = 0;
bool histCheio = false;

int mediaMovel(int valor) {
  historico[idxHist] = valor;
  idxHist = (idxHist + 1) % JANELA_MEDIA_LOCAL;
  if (idxHist == 0) histCheio = true;
  int n = histCheio ? JANELA_MEDIA_LOCAL : idxHist;
  long soma = 0;
  for (int i = 0; i < n; i++) soma += historico[i];
  return soma / n;
}

int lerLDR() {
  // Média de 5 leituras para reduzir ruído
  long soma = 0;
  for (int i = 0; i < 5; i++) {
    soma += analogRead(PINO_LDR);
    delay(2);
  }
  int valor = soma / 5;
  return LDR_INVERTIDO ? 1023 - valor : valor;
}

void olhos(bool esq, bool dir) {
  digitalWrite(PINO_OLHO_ESQ, esq ? HIGH : LOW);
  digitalWrite(PINO_OLHO_DIR, dir ? HIGH : LOW);
}

void moverServo(int alvo) {
  alvo = constrain(alvo, 30, 150);
  if (alvo != anguloServo) {
    anguloServo = alvo;
    cabeca.write(anguloServo);
  }
}

void processarComando(String cmd) {
  cmd.trim();
  if (cmd.startsWith("M:") && cmd.length() >= 3) {
    char novo = cmd.charAt(2);
    if (novo == 'N' || novo == 'A' || novo == 'C' || novo == 'F') {
      modo = novo;
      ultimoContatoPC = millis();
      if (autonomo) {
        autonomo = false;
        Serial.println("S:CONECTADO");
      }
    }
  }
}

void lerSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      processarComando(buffer);
      buffer = "";
    } else if (c != '\r' && buffer.length() < 20) {
      buffer += c;
    }
  }
}

void classificarLocal(int valor) {
  // Usado apenas quando o PC/IA está fora do ar
  if (valor < LIMITE_FALHA_BAIXO || valor >= 1018) modo = 'F';  // fio solto / curto
  else if (valor < LIMITE_CRITICO_LOCAL) modo = 'C';
  else if (valor < LIMITE_ATENCAO_LOCAL) modo = 'A';
  else modo = 'N';
}

void comportamento() {
  unsigned long agora = millis();

  switch (modo) {
    case 'N':  // Iluminação adequada: olhos acesos, cabeça centralizada
      olhos(true, true);
      moverServo(90);
      break;

    case 'A':  // Pouca luz: olhos piscam devagar, cabeça inclinada (desconfiada)
      if (agora - ultimoPisca > 700) {
        ultimoPisca = agora;
        estadoPisca = !estadoPisca;
        olhos(estadoPisca, estadoPisca);
      }
      moverServo(65);
      break;

    case 'C':  // Luz crítica: olhos piscam rápido, cabeça "procura" de um lado a outro
      if (agora - ultimoPisca > 150) {
        ultimoPisca = agora;
        estadoPisca = !estadoPisca;
        olhos(estadoPisca, estadoPisca);
      }
      if (agora - ultimoServo > 40) {
        ultimoServo = agora;
        int prox = anguloServo + passoServo;
        if (prox >= 135 || prox <= 45) passoServo = -passoServo;
        moverServo(prox);
      }
      break;

    case 'F':  // Falha no sensor: olhos alternam E/D, cabeça parada
      if (agora - ultimoPisca > 300) {
        ultimoPisca = agora;
        estadoPisca = !estadoPisca;
        olhos(estadoPisca, !estadoPisca);
      }
      moverServo(90);
      break;
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PINO_OLHO_ESQ, OUTPUT);
  pinMode(PINO_OLHO_DIR, OUTPUT);
  cabeca.attach(PINO_SERVO);
  cabeca.write(90);

  // Animação de inicialização: pisca os olhos 3x
  for (int i = 0; i < 3; i++) {
    olhos(true, true);  delay(150);
    olhos(false, false); delay(150);
  }
  Serial.println("S:PRONTO");
}

void loop() {
  unsigned long agora = millis();
  lerSerial();

  if (agora - ultimaLeitura >= INTERVALO_LEITURA_MS) {
    ultimaLeitura = agora;
    int valor = lerLDR();
    Serial.print("L:");
    Serial.println(valor);

    // Sem notícias do PC -> assume o controle sozinho
    if (!autonomo && agora - ultimoContatoPC > TIMEOUT_PC_MS) {
      autonomo = true;
      Serial.println("S:AUTONOMO");
    }
    int suave = mediaMovel(valor);
    if (autonomo) classificarLocal(suave);
  }

  comportamento();
}
