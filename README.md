# PDBGuard

[![Python](https://img.shields.io/badge/Python-3.10%E2%80%933.13-blue)](https://www.python.org/) [![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE) [![Security: offline](https://img.shields.io/badge/Cluster%20access-none-brightgreen)](docs/THREAT_MODEL.md)

**Planejamento conservador de janelas de manutenção Kubernetes com evidências explicáveis.**

O PDBGuard é uma ferramenta open-source de **segurança operacional, SRE e governança de mudanças** que examina, **sem conexão ao cluster**, um snapshot de `Nodes`, `Pods` e `PodDisruptionBudgets` (PDBs). Ela identifica impedimentos para `kubectl drain` e calcula o **maior conjunto de nós candidatos à manutenção simultânea** dentro das restrições que consegue observar.

**Não executa `kubectl`, não drena nós, não altera recursos e não afirma que o drain será seguro.** O algoritmo não simula scheduler, alterações de recursos, afinidades, capacidade, autoscaler, volumes persistentes, políticas de admission ou a própria API de Eviction. Todo resultado exige revisão humana e verificação atualizada no cluster.

## Por que existe?

Uma manutenção mal planejada pode derrubar réplicas suficientes para interromper serviços críticos. O Kubernetes oferece **PDBs** para limitar interrupções voluntárias. Porém, um PDB com `disruptionsAllowed=1` não autoriza uma operação simultânea que remova duas réplicas protegidas. Além disso, um único nó pode concentrar vários Pods do mesmo PDB. Inspecionar um nó isoladamente não revela todos os conflitos entre nós de uma mesma janela de manutenção.

O PDBGuard transforma um snapshot em uma avaliação reproduzível, rastreável e integrada ao CI. A proposta é diferente de RBAC scanning, segurança de APIs, FIM, backup, controle de egress e telemetria: **análise de indisponibilidade planejada por manutenção**.

## Recursos

| Área | Implementação |
|---|---|
| Inventário Kubernetes | Converte três JSONs do `kubectl get` em snapshot minimizado, sem depender do kubeconfig no tempo de análise |
| Evictions PDB | Usa `status.disruptionsAllowed`, geração observada, seletores de labels e políticas de Pods não prontos |
| Segurança fail-closed | Bloqueia sobreposição de PDB, geração desatualizada, Pod não gerenciado, `emptyDir` e `safe-to-evict=false` |
| Continuidade zonal | Preserva por padrão pelo menos um nó **Ready** por zona no conjunto simultâneo |
| Otimização exata | Busca determinística por subconjuntos (máximo 18 nós-alvo), maximizando os nós candidatos da janela |
| Evidências | Relatório legível, JSON estável e SARIF 2.1 para ferramentas de análise |
| Gestão de mudanças | Explica bloqueios individuais versus conflitos na mesma onda de manutenção |
| Segurança | Offline, Python stdlib, limite de arquivos, validação de tipos, recusa de chaves JSON duplicadas e symlink de saída |
| CI | Testes em Linux, Windows e macOS com Python 3.10–3.13 e artefatos de release condicionados ao CI |

## Instalação

Requisito: **Python 3.10+**. A CLI não exige bibliotecas de terceiros durante a execução.

```bash
python -m pip install .
pdbguard --version
# alternativa sem instalar: PYTHONPATH=src python -m pdbguard --help
```

Para instalar diretamente de um clone:

```bash
git clone https://github.com/felipewatter/pdbguard.git
cd pdbguard
python -m pip install .
```

### 1. Capturar um snapshot

Execute os comandos a seguir em um contexto **autorizado e somente leitura**, em máquina com `kubectl` instalado:

```bash
kubectl get nodes -o json > nodes.json
kubectl get pods --all-namespaces -o json > pods.json
kubectl get pdb --all-namespaces -o json > pdbs.json
```

**Atenção:** os JSONs originais podem conter nomes, labels e anotações internas. **Não faça commit desses arquivos reais.** O PDBGuard não instala operadores e não transmite dados para nenhum servidor.

Converta e minimize os arquivos:

```bash
pdbguard import --nodes nodes.json --pods pods.json --pdbs pdbs.json --out snapshot.json
```

### 2. Simular uma janela de manutenção

```bash
pdbguard plan snapshot.json --nodes worker-a worker-b worker-c
pdbguard plan snapshot.json --nodes worker-a worker-b --format json --out report.json
pdbguard plan snapshot.json --nodes worker-a worker-b --format sarif --out report.sarif
```

Exemplo interno, sem cluster:

```bash
pdbguard plan examples/snapshot.json --nodes worker-a worker-b worker-d
```

Saída resumida esperada:

```text
PDBGuard | OFFLINE ADVISORY (NOT A KUBERNETES SAFETY GUARANTEE)
Selected: 2/3 | Blocked: 0 | Deferred: 1
Proposed simultaneous maintenance wave: worker-a, worker-d
```

Os nomes são ordenados para garantir resultados estáveis independentemente da ordem fornecida.

### 3. Critérios opcionais

| Opção | Efeito |
|---|---|
| `--allow-missing-pdb` | Transforma falta de PDB de bloqueio em aviso. **Não cria proteção que não existe.** |
| `--ack-emptydir-loss` | Aceita explicitamente o risco de perda de dados temporários locais |
| `--ack-unmanaged` | Aceita explicitamente o risco de Pod sem controlador de recriação |
| `--min-ready-nodes-per-zone N` | Define quantos nós Ready devem continuar disponíveis por zona (padrão: 1) |
| `--format text\|json\|sarif` | Seleciona formato de relatório |
| `--out PATH` | Salva o relatório localmente, sem sobrescrever por link simbólico |

**Códigos de saída:** `0` = todos os nós-alvo foram selecionados, `1` = alguns bloqueados/adiados, `2` = entrada inválida ou falha de leitura/gravação. `0` **não significa autorização de manutenção**, apenas conformidade com as restrições implementadas.

## Modelo de decisão

1. Valida schema, identidade dos objetos, tipos, seletores e gerações PDB.
2. Associa Pods agendados ao nó e encontra PDBs por namespace + seletor Kubernetes.
3. Exclui Pods terminais/em terminação, DaemonSets e espelhos estáticos com avisos operacionais.
4. Aplica bloqueios conservadores a Pods não Running, sem controlador, com `emptyDir`, anotações não evacuar ou PDB sobreposto/desatualizado.
5. Calcula a **demanda de interrupções por nó e PDB**; Pods não prontos com `AlwaysAllow` não consomem orçamento, com alerta.
6. Remove da seleção nós que individualmente violariam cotas PDB ou o mínimo por zona.
7. Resolve, por enumeração exata limitada, a onda simultânea de maior cardinalidade sem exceder as quotas e limites de zona. Empates são resolvidos por nomes de nós em ordem lexicográfica.
8. Gera evidências incluindo `selected`, `deferred`, `blocked` e códigos de motivo. Nenhum comando de alteração é emitido.

### Exemplo de decisão

Três réplicas `web` em `worker-a`, `worker-b` e `worker-c`, PDB com `disruptionsAllowed=1`; `worker-d` não hospeda Pods afetados. O PDBGuard não seleciona simultaneamente `worker-a` e `worker-b`, mesmo que cada um, individualmente, respeite o limite de um Pod.

## Pressupostos e limitações — leia antes de usar

- **Fotografia no tempo:** mudanças após o snapshot podem invalidar qualquer conclusão; a API de Eviction continua sendo a fonte final de decisão.
- **Sem scheduler:** capacidade disponível, quotas, anti-affinity, topology spread, taints/tolerations, storage e controle de réplicas **não são simulados**.
- **Sem previsão de recuperação:** as cotas são tratadas como consumidas ao longo de uma onda simultânea; nenhum Pod é suposto reestabelecido entre nós.
- **Seletor PDB:** funciona com `matchLabels` e `matchExpressions` (`In`, `NotIn`, `Exists`, `DoesNotExist`) para PDBs `policy/v1`; seletores vazios em `policy/v1` abrangem todos os Pods do namespace. Objetos de outras versões não são avaliados como compatíveis automaticamente.
- **PDB status:** `status.disruptionsAllowed` e `status.observedGeneration` precisam estar presentes no snapshot; não calculamos uma cópia do controller do Kubernetes.
- **Pods não saudáveis:** `AlwaysAllow` é modelado conservadoramente; políticas do servidor, bloqueios externos e versão da API ainda devem ser conferidos.
- **DaemonSet:** assim como `kubectl drain --ignore-daemonsets`, Pods de DaemonSet não são tratados como evictáveis nesta simulação; podem continuar no nó.
- **Status do nó:** somente nós `Ready` podem ser escolhidos para avaliação; os demais exigem diagnóstico operacional específico.
- **Zona:** o limite considera **quantidade de nós Ready**, não disponibilidade real das réplicas em zonas ou quorum de bancos de dados.
- **Risco de dados:** `emptyDir` é tratado como bloqueador até reconhecimento explícito; PersistentVolumes e dependências externas não são inspecionados.
- **Representação parcial:** somente Pods agendados são importados. Snapshots em que existam Pods ausentes/desconhecidos ao usuário produzem conclusões incompletas.
- **Limite computacional:** máximo de 18 nós-alvo para garantir a busca exata de subconjuntos. Até 2.000 Nodes, 50.000 Pods e 4.000 PDBs por snapshot; tamanho de arquivo até 8 MiB.

## Segurança e privacidade

- Nunca forneça um `kubeconfig` à ferramenta; a CLI só lê arquivos JSON locais.
- Não versione snapshots de clusters reais: namespaces, nomes e labels podem revelar a arquitetura interna.
- Não execute automaticamente `kubectl drain` com base apenas em um relatório.
- Dados de entrada são tratados como não confiáveis: não há `eval`, execução de shell ou parsing YAML de runtime.
- O SARIF pode conter identificadores internos de nós, Pods e PDBs: classifique sua distribuição.
- Consulte [SECURITY.md](SECURITY.md) para divulgação responsável, [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) para o modelo de ameaças e [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) para os detalhes do algoritmo.

## Desenvolvimento e testes

```bash
python -m pip install -e .
python -m compileall -q src tests
python -m unittest discover -s tests -v
python -m pdbguard plan examples/snapshot.json --nodes worker-a worker-b worker-d --format json
```

GitHub Actions executa as verificações em 3 sistemas operacionais × 4 versões de Python, além da construção do pacote. A automação de release verifica que o SHA da execução aprovada do CI corresponde ao `HEAD` de `main` antes de criar a tag.

## Referências oficiais

- [Kubernetes — PodDisruptionBudgets](https://kubernetes.io/docs/tasks/run-application/configure-pdb/)
- [Kubernetes — Safely Drain a Node](https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/)
- [Kubernetes — API-initiated Eviction](https://kubernetes.io/docs/concepts/scheduling-eviction/api-eviction/)
- [Kubernetes — kubectl drain](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_drain/)

## Governança

Criado por **Felipe Watter** para estudo, engenharia defensiva, SRE e práticas responsáveis de gestão de mudanças.

Licença [MIT](LICENSE). Contribuições em [CONTRIBUTING.md](CONTRIBUTING.md). Registro de versões em [CHANGELOG.md](CHANGELOG.md).

> **PDBGuard informa decisões de manutenção; não substitui a API de Eviction, observabilidade em tempo real, validação do SRE, janela formal de mudança ou procedimentos de rollback.**
