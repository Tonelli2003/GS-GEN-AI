# Corpus — fontes oficiais (Prefeitura de São Paulo)

Data de consulta de todas as fontes: **19/11/2026**. Os textos foram extraídos das páginas oficiais e reorganizados em Markdown por seção, sem alterar fatos, prazos, telefones e valores. A data de publicação foi registrada quando a página a informava.

| # | id | Documento | Órgão | Categoria | Publicação | URL |
|---|---|---|---|---|---|---|
| 1 | tapa_buraco_sapopemba | Tapa-Buraco — carta de serviço | Subprefeitura Sapopemba | buraco_via | 11/12/2024 | https://prefeitura.sp.gov.br/web/sapopemba/w/zeladoria_urbana/116576 |
| 2 | tapa_buraco_ipiranga | Operação Tapa-Buraco — como solicitar | Subprefeitura Ipiranga | buraco_via | 17/08/2026 | https://prefeitura.sp.gov.br/web/ipiranga/w/opera%C3%A7%C3%A3o-tapa-buraco-no-ipiranga-saiba-como-solicitar-o-servi%C3%A7o |
| 3 | iluminacao_manutencao | Manutenção de iluminação pública | SP Regula | iluminacao | 06/03/2024 | https://prefeitura.sp.gov.br/web/spregula/w/iluminacao_publica/renovar/4603 |
| 4 | iluminacao_faq | Iluminação pública — perguntas frequentes | SP Regula | iluminacao | — | https://prefeitura.sp.gov.br/web/spregula/iluminacao_publica/perguntas_frequentes |
| 5 | iluminacao_ampliacao | Ampliação — novo ponto de iluminação | Prefeitura de SP | iluminacao | — | https://prefeitura.sp.gov.br/w/servico/ampliacao-novo-ponto-de-iluminacao-publica |
| 6 | psiu_barulho | PSIU — Programa Silêncio Urbano | SMSUB | barulho | — | https://prefeitura.sp.gov.br/web/subprefeituras/zeladoria/psiu |
| 7 | cata_bagulho | Operação Cata-Bagulho | Subprefeitura Sé | lixo_entulho | — | https://prefeitura.sp.gov.br/web/se/w/catabagulho/subse |
| 8 | ecopontos | Ecopontos | SMSUB | lixo_entulho | — | https://prefeitura.sp.gov.br/noticia/encontre-o-ecoponto-mais-perto-de-sua-casa |
| 9 | guia_zeladoria_smsub | Guia Temático de Serviços Públicos, 2ª ed. (zeladoria) | CGM/CODUSP · SMSUB | geral_zeladoria | — | https://prefeitura.sp.gov.br/documents/d/controladoria_geral/guia-codusp-versao-final-pdf |
| 10 | canais_sp156 | Canais SP156 — como solicitar e acompanhar | Sec. Mun. de Inovação e Tecnologia | atendimento_geral | — | https://prefeitura.sp.gov.br/web/inovacao/w/acesso_a_informacao/350229 |
| 11 | bocas_de_lobo | Limpeza de bocas de lobo, galerias e ramais | Subprefeitura Butantã (+ notícia do Chat SP156) | drenagem | 06/05/2022 | https://prefeitura.sp.gov.br/web/butanta/w/zeladoria_urbana/67875 |
| 12 | reparacao_danos | Reparação de Danos — indenização por danos materiais | Procuradoria Geral do Município | reparacao_danos | 22/07/2021 | https://prefeitura.sp.gov.br/web/procuradoria_geral/w/cejusc/315498 |

## Observações de qualidade

- **Desatualização:** a FAQ de iluminação (doc. 4) ainda cita a "Eletropaulo"; a distribuidora na capital hoje é a ENEL. O documento recebeu uma `nota_atualizacao`.
- **Conflito de prazos:** a carta de Tapa-Buraco da Sapopemba não informa prazo; o Guia Temático informa 45 dias. O assistente cita a fonte de cada dado.
- **Cobertura regional:** só há contatos de 4 subprefeituras (Sapopemba, Ipiranga, Sé e Butantã). Perguntas sobre outras regiões são tratadas por abstenção (verificação de lugar).
- **Documento adversarial:** `corpus/adversarial/99_documento_envenenado.md` não é fonte oficial; existe apenas para o teste de prompt injection indireto (SEC05).
