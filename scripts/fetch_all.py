#!/usr/bin/env python3
"""
全巴西犯罪新闻 RSS 抓取器（终极版）
- 50+ RSS 源（G1 全国 + UOL + Folha + Estadão + R7 + Metrópoles + 各地本地报）
- 只保留最近 7 天数据
- 解析发布时间，按时间倒序
- 输出 ISO 时间戳供前端显示"X 小时前"
"""
import urllib.request
import re
import json
import sys
import hashlib
import random
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

# 时效阈值：只保留最近 N 天
MAX_AGE_DAYS = 7

# ============================================================
# RSS 源（50+ 源）
# ============================================================
RSS_FEEDS = [
    # === G1 各州（27 个州，最稳定）===
    ("G1 Pernambuco", "https://g1.globo.com/rss/g1/pe/pernambuco/", "PE", "Recife"),
    ("G1 São Paulo", "https://g1.globo.com/rss/g1/sp/sao-paulo/", "SP", "São Paulo"),
    ("G1 Rio de Janeiro", "https://g1.globo.com/rss/g1/rj/rio-de-janeiro/", "RJ", "Rio de Janeiro"),
    ("G1 Bahia", "https://g1.globo.com/rss/g1/ba/bahia/", "BA", "Salvador"),
    ("G1 Ceará", "https://g1.globo.com/rss/g1/ce/ceara/", "CE", "Fortaleza"),
    ("G1 Minas Gerais", "https://g1.globo.com/rss/g1/mg/minas-gerais/", "MG", "Belo Horizonte"),
    ("G1 Rio Grande do Sul", "https://g1.globo.com/rss/g1/rs/rio-grande-do-sul/", "RS", "Porto Alegre"),
    ("G1 Paraná", "https://g1.globo.com/rss/g1/pr/parana/", "PR", "Curitiba"),
    ("G1 Distrito Federal", "https://g1.globo.com/rss/g1/df/distrito-federal/", "DF", "Brasília"),
    ("G1 Santa Catarina", "https://g1.globo.com/rss/g1/sc/santa-catarina/", "SC", "Florianópolis"),
    ("G1 Goiás", "https://g1.globo.com/rss/g1/go/goias/", "GO", "Goiânia"),
    ("G1 Espírito Santo", "https://g1.globo.com/rss/g1/es/espirito-santo/", "ES", "Vitória"),
    ("G1 Pará", "https://g1.globo.com/rss/g1/pa/para/", "PA", "Belém"),
    ("G1 Amazonas", "https://g1.globo.com/rss/g1/am/amazonas/", "AM", "Manaus"),
    ("G1 Maranhão", "https://g1.globo.com/rss/g1/ma/maranhao/", "MA", "São Luís"),
    ("G1 Paraíba", "https://g1.globo.com/rss/g1/pb/paraiba/", "PB", "João Pessoa"),
    ("G1 Rio Grande do Norte", "https://g1.globo.com/rss/g1/rn/rio-grande-do-norte/", "RN", "Natal"),
    ("G1 Alagoas", "https://g1.globo.com/rss/g1/al/alagoas/", "AL", "Maceió"),
    ("G1 Sergipe", "https://g1.globo.com/rss/g1/se/sergipe/", "SE", "Aracaju"),
    ("G1 Piauí", "https://g1.globo.com/rss/g1/pi/piaui/", "PI", "Teresina"),
    ("G1 Mato Grosso", "https://g1.globo.com/rss/g1/mt/mato-grosso/", "MT", "Cuiabá"),
    ("G1 Mato Grosso do Sul", "https://g1.globo.com/rss/g1/ms/mato-grosso-do-sul/", "MS", "Campo Grande"),
    ("G1 Tocantins", "https://g1.globo.com/rss/g1/to/tocantins/", "TO", "Palmas"),
    ("G1 Acre", "https://g1.globo.com/rss/g1/ac/acre/", "AC", "Rio Branco"),
    ("G1 Rondônia", "https://g1.globo.com/rss/g1/ro/rondonia/", "RO", "Porto Velho"),
    ("G1 Amapá", "https://g1.globo.com/rss/g1/ap/amapa/", "AP", "Macapá"),
    ("G1 Roraima", "https://g1.globo.com/rss/g1/rr/roraima/", "RR", "Boa Vista"),

    # === G1 全国版块（综合）===
    ("G1 Brasil", "https://g1.globo.com/rss/g1/", "BR", "Brasil"),
    ("G1 Política", "https://g1.globo.com/rss/g1/politica/", "BR", "Brasil"),

    # === Folha de São Paulo ===
    ("Folha Cotidiano", "https://feeds.folha.uol.com.br/cotidiano/rss091.xml", "SP", "São Paulo"),

    # === UOL Notícias ===
    ("UOL Cotidiano", "https://rss.uol.com.br/feed/noticias.xml", "BR", "São Paulo"),

    # === R7 ===
    # [DEAD] ("R7 Cidades", "https://noticias.r7.com/cidades/feed.xml", "BR", "São Paulo"),
    # [DEAD] ("R7 SP", "https://noticias.r7.com/sao-paulo/feed.xml", "SP", "São Paulo"),
    # [DEAD] ("R7 RJ", "https://noticias.r7.com/rio-de-janeiro/feed.xml", "RJ", "Rio de Janeiro"),

    # === Estadão ===
    # [DEAD] ("Estadão Brasil", "https://www.estadao.com.br/rss/brasil.xml", "BR", "São Paulo"),

    # === 巴西利亚地区 ===
    ("Metrópoles DF", "https://www.metropoles.com/feed", "DF", "Brasília"),

    # === 东北地区本地报 ===
    # [DEAD] ("NE10", "https://blogs.ne10.uol.com.br/feed/", "PE", "Recife"),
    # [DEAD] ("Jornal do Commercio", "https://jc.ne10.uol.com.br/feed/", "PE", "Recife"),

    # === 南部地区本地报 ===
    # [DEAD] ("Gaúcha ZH", "https://gauchazh.clicrbs.com.br/rss.xml", "RS", "Porto Alegre"),

    # === 巴伊亚 ===
    ("A Tarde", "https://www.atarde.com.br/rss", "BA", "Salvador"),

    # === 米纳斯吉拉斯 ===
    # [DEAD] ("Estado de Minas", "https://www.em.com.br/rss/noticia/gerais.xml", "MG", "Belo Horizonte"),

    # === 圣保罗本地 ===
    ("Diário SP", "https://www.diariosp.com.br/feed/", "SP", "São Paulo"),

    # ========================================
    # 🆕 G1 城市级 RSS（更细！每个城市单独抓）
    # ========================================
    ("G1 Recife", "https://g1.globo.com/rss/g1/pe/pernambuco/recife/", "PE", "Recife"),
    ("G1 Caruaru", "https://g1.globo.com/rss/g1/pe/caruaru-regiao/", "PE", "Caruaru"),
    ("G1 Petrolina", "https://g1.globo.com/rss/g1/pe/petrolina-regiao/", "PE", "Petrolina"),
    ("G1 Campinas", "https://g1.globo.com/rss/g1/sp/campinas-regiao/", "SP", "Campinas"),
    ("G1 Santos", "https://g1.globo.com/rss/g1/sp/santos-regiao/", "SP", "Santos"),
    ("G1 Ribeirão Preto", "https://g1.globo.com/rss/g1/sp/ribeirao-preto-franca/", "SP", "Ribeirão Preto"),
    ("G1 São José do Rio Preto", "https://g1.globo.com/rss/g1/sp/sao-jose-do-rio-preto-aracatuba/", "SP", "São José do Rio Preto"),
    ("G1 Sorocaba", "https://g1.globo.com/rss/g1/sp/sorocaba-jundiai/", "SP", "Sorocaba"),
    ("G1 Bauru", "https://g1.globo.com/rss/g1/sp/bauru-marilia/", "SP", "Bauru"),
    ("G1 Vale do Paraíba", "https://g1.globo.com/rss/g1/sp/vale-do-paraiba-regiao/", "SP", "São José dos Campos"),
    ("G1 Presidente Prudente", "https://g1.globo.com/rss/g1/sp/presidente-prudente-regiao/", "SP", "Presidente Prudente"),
    ("G1 Itapetininga", "https://g1.globo.com/rss/g1/sp/itapetininga-regiao/", "SP", "Itapetininga"),
    ("G1 Norte SP", "https://g1.globo.com/rss/g1/sp/sao-carlos-regiao/", "SP", "São Carlos"),

    ("G1 Rio Norte/Sul", "https://g1.globo.com/rss/g1/rj/regiao-dos-lagos/", "RJ", "Cabo Frio"),
    ("G1 Norte Fluminense", "https://g1.globo.com/rss/g1/rj/norte-fluminense/", "RJ", "Campos dos Goytacazes"),
    ("G1 Sul do RJ", "https://g1.globo.com/rss/g1/rj/sul-do-rio-costa-verde/", "RJ", "Volta Redonda"),
    ("G1 Serra RJ", "https://g1.globo.com/rss/g1/rj/regiao-serrana/", "RJ", "Petrópolis"),

    ("G1 Triângulo Mineiro", "https://g1.globo.com/rss/g1/mg/triangulo-mineiro/", "MG", "Uberlândia"),
    ("G1 Sul de MG", "https://g1.globo.com/rss/g1/mg/sul-de-minas/", "MG", "Pouso Alegre"),
    ("G1 Zona da Mata", "https://g1.globo.com/rss/g1/mg/zona-da-mata/", "MG", "Juiz de Fora"),
    ("G1 Vales MG", "https://g1.globo.com/rss/g1/mg/vales-mg/", "MG", "Governador Valadares"),
    ("G1 Centro-Oeste MG", "https://g1.globo.com/rss/g1/mg/centro-oeste/", "MG", "Divinópolis"),

    ("G1 Norte BA", "https://g1.globo.com/rss/g1/ba/petrolina-juazeiro/", "BA", "Juazeiro"),
    ("G1 Sul BA", "https://g1.globo.com/rss/g1/ba/sul-da-bahia/", "BA", "Itabuna"),
    ("G1 Sudoeste BA", "https://g1.globo.com/rss/g1/ba/sudoeste/", "BA", "Vitória da Conquista"),

    ("G1 Norte e Noroeste PR", "https://g1.globo.com/rss/g1/pr/norte-noroeste/", "PR", "Maringá"),
    ("G1 Oeste PR", "https://g1.globo.com/rss/g1/pr/oeste-sudoeste/", "PR", "Cascavel"),
    ("G1 Campos Gerais", "https://g1.globo.com/rss/g1/pr/campos-gerais-sul/", "PR", "Ponta Grossa"),
    ("G1 Londrina", "https://g1.globo.com/rss/g1/pr/norte-noroeste/", "PR", "Londrina"),

    # === SC 城市 ===
    ("G1 SC Vale do Itajaí", "https://g1.globo.com/rss/g1/sc/santa-catarina/", "SC", "Blumenau"),

    # === RS 城市 ===
    ("G1 RS Centro Oeste", "https://g1.globo.com/rss/g1/rs/rio-grande-do-sul/", "RS", "Santa Maria"),

    # ========================================
    # 🆕 R7 各州（之前缺）
    # ========================================
    # [DEAD] ("R7 MG", "https://noticias.r7.com/minas-gerais/feed.xml", "MG", "Belo Horizonte"),
    # [DEAD] ("R7 BA", "https://noticias.r7.com/bahia/feed.xml", "BA", "Salvador"),
    # [DEAD] ("R7 PR", "https://noticias.r7.com/parana/feed.xml", "PR", "Curitiba"),
    # [DEAD] ("R7 PE", "https://noticias.r7.com/pernambuco/feed.xml", "PE", "Recife"),
    # [DEAD] ("R7 RS", "https://noticias.r7.com/rio-grande-do-sul/feed.xml", "RS", "Porto Alegre"),
    # [DEAD] ("R7 GO", "https://noticias.r7.com/goias/feed.xml", "GO", "Goiânia"),
    # [DEAD] ("R7 DF", "https://noticias.r7.com/distrito-federal/feed.xml", "DF", "Brasília"),

    # ========================================
    # 🆕 大型综合媒体
    # ========================================
    ("BBC Brasil", "https://feeds.bbci.co.uk/portuguese/rss.xml", "BR", "São Paulo"),
    # [DEAD] ("CNN Brasil Nacional", "https://www.cnnbrasil.com.br/nacional/feed/", "BR", "São Paulo"),
    ("Carta Capital", "https://www.cartacapital.com.br/feed/", "BR", "São Paulo"),
    ("Veja Brasil", "https://veja.abril.com.br/feed/", "BR", "São Paulo"),
    ("ISTOÉ", "https://istoe.com.br/feed/", "BR", "São Paulo"),
    # [DEAD] ("Exame Brasil", "https://exame.com/feed/", "BR", "São Paulo"),
    ("Poder360", "https://www.poder360.com.br/feed/", "DF", "Brasília"),
    ("Agência Brasil", "https://agenciabrasil.ebc.com.br/rss.xml", "BR", "Brasília"),

    # ========================================
    # 🆕 Folha 各版块
    # ========================================
    ("Folha São Paulo", "https://feeds.folha.uol.com.br/saopaulo/rss091.xml", "SP", "São Paulo"),
    ("Folha Brasil", "https://feeds.folha.uol.com.br/poder/rss091.xml", "BR", "Brasília"),

    # ========================================
    # 🆕 各州地方报纸
    # ========================================
    # PE
    # [DEAD] ("Folha PE", "https://www.folhape.com.br/rss/", "PE", "Recife"),
    # [DEAD] ("Diário PE", "https://www.diariodepernambuco.com.br/rss/diariodepernambuco.xml", "PE", "Recife"),
    # CE
    # [DEAD] ("OPovo CE", "https://www.opovo.com.br/rss/feed/", "CE", "Fortaleza"),
    # [DEAD] ("Diário do Nordeste", "https://diariodonordeste.verdesmares.com.br/rss/", "CE", "Fortaleza"),
    # RJ
    # [DEAD] ("O Dia RJ", "https://odia.ig.com.br/rss/", "RJ", "Rio de Janeiro"),
    # [DEAD] ("O Globo RJ", "https://oglobo.globo.com/rss/rio", "RJ", "Rio de Janeiro"),
    ("Extra RJ", "https://extra.globo.com/rss.xml", "RJ", "Rio de Janeiro"),
    # SP
    # [DEAD] ("Diário Região", "https://www.diarioregiao.com.br/rss/", "SP", "São José do Rio Preto"),
    # PR
    # [DEAD] ("Gazeta do Povo", "https://www.gazetadopovo.com.br/rss/parana", "PR", "Curitiba"),
    ("Bem Paraná", "https://www.bemparana.com.br/rss/", "PR", "Curitiba"),
    # SC
    # [DEAD] ("NSC Total", "https://www.nsctotal.com.br/feed/", "SC", "Florianópolis"),
    # ES
    # [DEAD] ("A Gazeta ES", "https://www.agazeta.com.br/rss/", "ES", "Vitória"),
    # GO
    ("Jornal Opção GO", "https://www.jornalopcao.com.br/feed/", "GO", "Goiânia"),
    # AM
    # [DEAD] ("Em Tempo AM", "https://d24am.com/rss.xml", "AM", "Manaus"),
    ("Portal Amazônia", "https://portalamazonia.com/feed/", "AM", "Manaus"),
    # PA
    # [DEAD] ("Diário do Pará", "https://www.diariodopara.com.br/rss/", "PA", "Belém"),
    # [DEAD] ("Liberal PA", "https://www.oliberal.com/feed/", "PA", "Belém"),
    # MA
    ("Imirante MA", "https://imirante.com/rss/", "MA", "São Luís"),
    # RN
    # [DEAD] ("Tribuna do Norte", "https://www.tribunadonorte.com.br/rss.xml", "RN", "Natal"),
    # AL
    # [DEAD] ("Gazeta de Alagoas", "https://d.gazetadealagoas.com.br/feed/", "AL", "Maceió"),
    # [DEAD] ("Cada Minuto AL", "https://www.cadaminuto.com.br/rss/", "AL", "Maceió"),
    # MT
    # [DEAD] ("Gazeta Digital MT", "https://www.gazetadigital.com.br/rss/", "MT", "Cuiabá"),
    # MS
    ("Campo Grande News", "https://www.campograndenews.com.br/rss/", "MS", "Campo Grande"),
    # AC/RO
    # [DEAD] ("Gente de Opinião", "https://www.gentedeopiniao.com.br/feed/", "RO", "Porto Velho"),
    
    # === 全国警务/犯罪类专栏 ===
    # [DEAD] ("UOL Cidades", "https://rss.uol.com.br/feed/cotidiano.xml", "BR", "São Paulo"),
    # [DEAD] ("UOL Polícia", "https://noticias.uol.com.br/cotidiano/index.rss", "BR", "São Paulo"),
    # [DEAD] ("Terra Brasil", "https://rss.terra.com.br/0,,EI306,00.xml", "BR", "São Paulo"),
    # [DEAD] ("Yahoo Brasil", "https://br.noticias.yahoo.com/rss/brasil", "BR", "São Paulo"),

    # ========================================
    # 🆕🆕 第三波：30+ 新 RSS 源
    # ========================================
    # 小报 / 民生类
    ("Brasil 247", "https://www.brasil247.com/rss", "BR", "São Paulo"),
    # [DEAD] ("Brasil de Fato", "https://www.brasildefato.com.br/rss2.xml", "BR", "São Paulo"),
    ("Carta Capital", "https://www.cartacapital.com.br/feed/", "BR", "São Paulo"),
    ("Veja", "https://veja.abril.com.br/feed", "BR", "São Paulo"),
    ("IstoÉ", "https://istoe.com.br/feed/", "BR", "São Paulo"),
    # [DEAD] ("Exame", "https://exame.com/feed/", "BR", "São Paulo"),
    ("BBC Brasil", "https://feeds.bbci.co.uk/portuguese/rss.xml", "BR", "São Paulo"),
    # [DEAD] ("DW Brasil", "https://rss.dw.com/rdf/rss-br-all", "BR", "São Paulo"),
    ("CNN Brasil", "https://www.cnnbrasil.com.br/feed/", "BR", "São Paulo"),
    ("Poder360", "https://www.poder360.com.br/feed/", "BR", "Brasília"),

    # G1 更多城市级
    ("G1 Santos", "https://g1.globo.com/rss/g1/sp/santos-regiao/", "SP", "Santos"),
    ("G1 Sorocaba", "https://g1.globo.com/rss/g1/sp/sorocaba-jundiai/", "SP", "Sorocaba"),
    ("G1 Ribeirão", "https://g1.globo.com/rss/g1/sp/ribeirao-preto-franca/", "SP", "Ribeirão Preto"),
    ("G1 Bauru", "https://g1.globo.com/rss/g1/sp/bauru-marilia/", "SP", "Bauru"),
    ("G1 Vale", "https://g1.globo.com/rss/g1/sp/vale-do-paraiba-regiao/", "SP", "São José dos Campos"),
    ("G1 Triângulo", "https://g1.globo.com/rss/g1/mg/triangulo-mineiro/", "MG", "Uberlândia"),
    ("G1 Sul MG", "https://g1.globo.com/rss/g1/mg/sul-de-minas/", "MG", "Pouso Alegre"),
    ("G1 Zona da Mata", "https://g1.globo.com/rss/g1/mg/zona-da-mata/", "MG", "Juiz de Fora"),
    ("G1 Norte RJ", "https://g1.globo.com/rss/g1/rj/norte-fluminense/", "RJ", "Campos dos Goytacazes"),
    ("G1 Região dos Lagos", "https://g1.globo.com/rss/g1/rj/regiao-dos-lagos/", "RJ", "Cabo Frio"),
    ("G1 Sul RJ", "https://g1.globo.com/rss/g1/rj/sul-do-rio-costa-verde/", "RJ", "Volta Redonda"),
    ("G1 Oeste BA", "https://g1.globo.com/rss/g1/ba/oeste/", "BA", "Salvador"),
    ("G1 Sudoeste BA", "https://g1.globo.com/rss/g1/ba/sudoeste/", "BA", "Itabuna"),
    ("G1 Norte SC", "https://g1.globo.com/rss/g1/sc/santa-catarina/norte-catarinense/", "SC", "Joinville"),
    ("G1 Vale Itajaí", "https://g1.globo.com/rss/g1/sc/santa-catarina/vale-do-itajai/", "SC", "Blumenau"),
    ("G1 Centro Oeste PR", "https://g1.globo.com/rss/g1/pr/oeste-sudoeste/", "PR", "Cascavel"),
    ("G1 Norte PR", "https://g1.globo.com/rss/g1/pr/norte-noroeste/", "PR", "Maringá"),

    # 国际/地方更多
    # [DEAD] ("O Tempo", "https://www.otempo.com.br/rss/cidades", "MG", "Belo Horizonte"),
    # [DEAD] ("Hoje em Dia", "https://www.hojeemdia.com.br/rss", "MG", "Belo Horizonte"),
    # [DEAD] ("Folha Vitória", "https://www.folhavitoria.com.br/rss/", "ES", "Vitória"),
    # [DEAD] ("Correio Braziliense", "https://www.correiobraziliense.com.br/rss/cidadesdf.xml", "DF", "Brasília"),
    # [DEAD] ("Correio do Povo", "https://www.correiodopovo.com.br/rss/policia", "RS", "Porto Alegre"),
    # [DEAD] ("Zero Hora Polícia", "https://gauchazh.clicrbs.com.br/seguranca/rss.xml", "RS", "Porto Alegre"),
    # [DEAD] ("Diário Catarinense", "https://www.nsctotal.com.br/seguranca/feed/", "SC", "Florianópolis"),
    # [DEAD] ("Tribuna PR", "https://www.tribunapr.com.br/rss/policia/", "PR", "Curitiba"),
]

# ============================================================
# 🆕 Google News RSS — 按城市定向搜索（覆盖面大杀器）
# 每个城市一个专属 RSS，搜索犯罪相关关键词
# Google News RSS 超稳定 + 聚合了上千个巴西媒体源
# ============================================================
import urllib.parse as _up

# (城市, 州, 城市精确名用于搜索)
GNEWS_CITIES = [
    # 大城市 / 首府
    ("Recife", "PE"), ("São Paulo", "SP"), ("Rio de Janeiro", "RJ"),
    ("Salvador", "BA"), ("Fortaleza", "CE"), ("Belo Horizonte", "MG"),
    ("Porto Alegre", "RS"), ("Curitiba", "PR"), ("Brasília", "DF"),
    ("Florianópolis", "SC"), ("Goiânia", "GO"), ("Vitória", "ES"),
    ("Belém", "PA"), ("Manaus", "AM"), ("São Luís", "MA"),
    ("João Pessoa", "PB"), ("Natal", "RN"), ("Maceió", "AL"),
    ("Aracaju", "SE"), ("Teresina", "PI"), ("Cuiabá", "MT"),
    ("Campo Grande", "MS"), ("Palmas", "TO"), ("Rio Branco", "AC"),
    ("Porto Velho", "RO"), ("Macapá", "AP"), ("Boa Vista", "RR"),
    # PE 内陆
    ("Caruaru", "PE"), ("Petrolina", "PE"), ("Olinda", "PE"), ("Jaboatão", "PE"),
    # SP 都市圈 / 内陆
    ("Osasco", "SP"), ("Guarulhos", "SP"), ("Campinas", "SP"),
    ("Santo André", "SP"), ("Santos", "SP"), ("Ribeirão Preto", "SP"),
    ("São José do Rio Preto", "SP"), ("Sorocaba", "SP"), ("Bauru", "SP"),
    ("São José dos Campos", "SP"), ("Presidente Prudente", "SP"),
    ("Itapetininga", "SP"), ("São Carlos", "SP"),
    # RJ
    ("São Gonçalo", "RJ"), ("Niterói", "RJ"), ("Cabo Frio", "RJ"),
    ("Campos dos Goytacazes", "RJ"), ("Volta Redonda", "RJ"), ("Petrópolis", "RJ"),
    # MG
    ("Contagem", "MG"), ("Uberlândia", "MG"), ("Juiz de Fora", "MG"),
    ("Pouso Alegre", "MG"), ("Governador Valadares", "MG"), ("Divinópolis", "MG"),
    # BA
    ("Feira de Santana", "BA"), ("Camaçari", "BA"), ("Itabuna", "BA"),
    ("Juazeiro", "BA"), ("Porto Seguro", "BA"),
    # PR
    ("Londrina", "PR"), ("Maringá", "PR"), ("Cascavel", "PR"), ("Ponta Grossa", "PR"),
    # SC
    ("Joinville", "SC"), ("Blumenau", "SC"),
    # RS
    ("Caxias do Sul", "RS"), ("Pelotas", "RS"), ("Santa Maria", "RS"),
]

# 每个城市生成 2 个不同关键词组合的 Google News RSS，提升覆盖
_GNEWS_QUERIES = [
    'crime+OR+homicidio+OR+assalto+OR+roubo',
    'tráfico+OR+morto+OR+baleado+OR+polícia',
]

for _city, _state in GNEWS_CITIES:
    for _i, _q in enumerate(_GNEWS_QUERIES, start=1):
        _city_q = _up.quote(f'"{_city}"')
        _url = (
            f"https://news.google.com/rss/search?"
            f"q={_q}+{_city_q}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
        )
        RSS_FEEDS.append(
            (f"GNews {_city} #{_i}", _url, _state, _city)
        )

# 全国级 Google News（兜底）
RSS_FEEDS.extend([
    ("GNews Brasil Crime",
     "https://news.google.com/rss/search?q=crime+brasil&hl=pt-BR&gl=BR&ceid=BR:pt-419",
     "BR", "Brasil"),
    ("GNews Brasil Homicídio",
     "https://news.google.com/rss/search?q=homicidio+brasil&hl=pt-BR&gl=BR&ceid=BR:pt-419",
     "BR", "Brasil"),
    ("GNews Brasil Tráfico",
     "https://news.google.com/rss/search?q=tráfico+drogas+brasil&hl=pt-BR&gl=BR&ceid=BR:pt-419",
     "BR", "Brasil"),
    ("GNews Brasil Operação",
     "https://news.google.com/rss/search?q=operação+policial+brasil&hl=pt-BR&gl=BR&ceid=BR:pt-419",
     "BR", "Brasil"),
    ("GNews Brasil Feminicídio",
     "https://news.google.com/rss/search?q=feminicídio+brasil&hl=pt-BR&gl=BR&ceid=BR:pt-419",
     "BR", "Brasil"),
])

# ============================================================
# 城市坐标
# ============================================================
CITY_COORDS = {
    'Recife': (-8.0476, -34.8770), 'São Paulo': (-23.5505, -46.6333),
    'Rio de Janeiro': (-22.9068, -43.1729), 'Salvador': (-12.9714, -38.5014),
    'Fortaleza': (-3.7172, -38.5433), 'Belo Horizonte': (-19.9167, -43.9345),
    'Porto Alegre': (-30.0346, -51.2177), 'Curitiba': (-25.4284, -49.2733),
    'Brasília': (-15.7975, -47.8919), 'Florianópolis': (-27.5954, -48.5480),
    'Goiânia': (-16.6869, -49.2648), 'Vitória': (-20.3155, -40.3128),
    'Belém': (-1.4558, -48.4902), 'Manaus': (-3.1190, -60.0217),
    'São Luís': (-2.5391, -44.2829), 'João Pessoa': (-7.1195, -34.8450),
    'Natal': (-5.7945, -35.2110), 'Maceió': (-9.6498, -35.7089),
    'Aracaju': (-10.9472, -37.0731), 'Teresina': (-5.0892, -42.8019),
    'Cuiabá': (-15.6014, -56.0979), 'Campo Grande': (-20.4486, -54.6295),
    'Palmas': (-10.1843, -48.3338), 'Rio Branco': (-9.9754, -67.8249),
    'Porto Velho': (-8.7619, -63.9039), 'Macapá': (0.0349, -51.0694),
    'Boa Vista': (2.8235, -60.6758),
    'Caruaru': (-8.2842, -35.9760), 'Osasco': (-23.5325, -46.7919),
    'São Gonçalo': (-22.8268, -43.0537), 'Niterói': (-22.8833, -43.1036),
    'Porto Seguro': (-16.4497, -39.0647), 'Guarulhos': (-23.4628, -46.5333),
    'Campinas': (-22.9099, -47.0626), 'Santo André': (-23.6739, -46.5390),
    'Olinda': (-7.9886, -34.8399), 'Jaboatão': (-8.1130, -35.0150),
    'Feira de Santana': (-12.2667, -38.9667), 'Camaçari': (-12.6996, -38.3243),
    'Contagem': (-19.9319, -44.0531), 'Uberlândia': (-18.9186, -48.2772),
    'Juiz de Fora': (-21.7595, -43.3350), 'Londrina': (-23.3045, -51.1696),
    'Maringá': (-23.4205, -51.9333), 'Joinville': (-26.3045, -48.8487),
    'Blumenau': (-26.9194, -49.0661), 'Caxias do Sul': (-29.1685, -51.1796),
    'Pelotas': (-31.7654, -52.3376), 'Santa Maria': (-29.6914, -53.8008),
    # 🆕 新增城市
    'Petrolina': (-9.3891, -40.5030), 'Juazeiro': (-9.4163, -40.4986),
    'Santos': (-23.9608, -46.3331), 'Ribeirão Preto': (-21.1775, -47.8103),
    'São José do Rio Preto': (-20.8113, -49.3758), 'Sorocaba': (-23.5018, -47.4581),
    'Bauru': (-22.3145, -49.0581), 'São José dos Campos': (-23.2237, -45.9009),
    'Presidente Prudente': (-22.1208, -51.3889), 'Itapetininga': (-23.5915, -48.0535),
    'São Carlos': (-22.0087, -47.8909), 'Cabo Frio': (-22.8894, -42.0286),
    'Campos dos Goytacazes': (-21.7545, -41.3244), 'Volta Redonda': (-22.5202, -44.0996),
    'Petrópolis': (-22.5050, -43.1786), 'Pouso Alegre': (-22.2299, -45.9358),
    'Governador Valadares': (-18.8512, -41.9494), 'Divinópolis': (-20.1446, -44.8912),
    'Itabuna': (-14.7853, -39.2803), 'Cascavel': (-24.9555, -53.4552),
    'Ponta Grossa': (-25.0916, -50.1668),
    'Brasil': (-14.235, -51.925),
}

# ============================================================
# 关键词
# ============================================================
CRIME_KW = [
    # 抢劫盗窃
    'roubo', 'roub', 'assalt', 'furto', 'furt', 'latrocín', 'latrocin',
    'arrastão', 'arrastao', 'saqueio', 'saque',
    # 杀人
    'homicid', 'morto', 'morta', 'mortos', 'mortas', 'morre', 'morreu',
    'baleado', 'baleada', 'baleados', 'tiro', 'tiros', 'matou', 'matar', 'matam',
    'esfaqueado', 'esfaqueada', 'facad', 'apunhal',
    'execução', 'executado', 'executada', 'chacin', 'massacre',
    'cadáver', 'corpo encontrado', 'corpos encontrados', 'morto a tiros',
    # 性暴力 / 妇女
    'estupro', 'estupr', 'feminic', 'violência sexual', 'abuso sexual',
    'pedofilia', 'aliciamento',
    # 绑架 / 劫持
    'sequestr', 'rapto', 'cativeiro', 'refém', 'refens',
    # 毒品
    'tráfico', 'trafico', 'drogas', 'narcotráfico', 'cocaín', 'maconha', 'crack',
    'entorpecente', 'apreensão de drogas',
    # 警方行动
    'apreendid', 'preso', 'presa', 'presos', 'presas', 'detido', 'detida',
    'preso em flagrante', 'operação policial', 'confronto', 'troca de tiros',
    'fugitivo', 'foragido',
    # 暴力 / 家暴
    'agressão', 'agredid', 'espancado', 'espancada', 'lesão corporal',
    'violência doméstica', 'tentativa de homicídio', 'tentativa de assassinato',
    'ameaça', 'ameaçou',
    # 综合
    'crime', 'criminoso', 'bandido', 'quadrilha', 'facção', 'milícia',
    'pcc', 'cv ', 'comando vermelho', 'organização criminosa',
    'tortura', 'tortur', 'incêndio criminoso', 'arma de fogo', 'pistola',
    'corrupção', 'fraude', 'estelionato', 'golpe',
    # 🆕 汽车相关犯罪
    'roubo de carro', 'roubo de veículo', 'roubo de moto', 'carro roubado',
    'moto roubada', 'veículo roubado', 'recupera veículo', 'carro furtado',
    'desmanche', 'receptação', 'racha', 'embriaguez ao volante', 'atropela',
    'atropelado', 'atropelada', 'fuga após acidente',
    # 🆕 未成年相关
    'adolescente apreendid', 'menor apreendid', 'menor preso',
    'criança morta', 'criança baleada', 'adolescente morto', 'adolescente baleado',
    'ato infracional', 'aliciamento de menor', 'exploração de menor',
]
EXCLUDE_KW = [
    # 节日（避免「quadrilha junina = 圣若昂方阵舞」误判）
    'junina', 'juninas', 'são joão', 'forró', 'arraial',
    # 体育
    'futebol', 'campeonato brasileiro', 'libertadores', 'copa do mundo',
]
CRIME_TYPES = {
    'homicidio': ['homicid', 'morto', 'morta', 'baleado', 'baleada', 'matou',
                  'esfaqueado', 'facad', 'feminic', 'execução', 'chacin', 'massacre',
                  'cadáver', 'corpo encontrado', 'morre', 'morreu', 'tentativa de homicídio',
                  'apunhal', 'tortura', 'tortur'],
    'roubo': ['roubo', 'roub', 'assalt', 'arrastão', 'arrastao', 'latrocín', 'latrocin'],
    'furto': ['furto', 'furt'],
    'estupro': ['estupro', 'estupr', 'violência sexual', 'abuso sexual', 'pedofilia'],
    'trafico': ['tráfico', 'trafico', 'drogas', 'narcotráfico', 'cocaín', 'maconha', 'crack',
                'entorpecente'],
    'sequestro': ['sequestr', 'rapto', 'cativeiro', 'refém', 'refens'],
    'violencia': ['agressão', 'agredid', 'espancado', 'espancada', 'lesão corporal',
                  'violência doméstica', 'ameaça', 'ameaçou'],
    'policia':   ['operação policial', 'confronto', 'troca de tiros', 'preso em flagrante',
                  'fugitivo', 'foragido', 'apreensão'],
    'faccao':    ['facção', 'milícia', 'pcc', 'comando vermelho', 'organização criminosa',
                  'quadrilha'],
    'fraude':    ['fraude', 'estelionato', 'golpe', 'corrupção'],
    # 🆕 汽车相关
    'veiculo':   ['roubo de carro', 'roubo de veículo', 'roubo de moto',
                  'carro roubado', 'moto roubada', 'veículo roubado',
                  'recupera veículo', 'carro furtado', 'desmanche',
                  'receptação', 'racha', 'embriaguez ao volante',
                  'atropela', 'atropelado', 'atropelada', 'fuga após acidente'],
    # 🆕 未成年
    'menor':     ['adolescente apreendid', 'menor apreendid', 'menor preso',
                  'criança morta', 'criança baleada', 'adolescente morto',
                  'adolescente baleado', 'ato infracional',
                  'aliciamento', 'aliciamento de menor', 'exploração de menor'],
}

# ============================================================
# 工具函数
# ============================================================
def fetch_url(url, timeout=10):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/rss+xml, application/xml, text/xml, */*;q=0.9',
        'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.5',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode('utf-8', errors='ignore')
    except Exception as e:
        return None

def fetch_one_feed(feed):
    """并行任务：抓单个 feed → 返回 (feed, xml)"""
    source, url, state, default_city = feed
    return feed, fetch_url(url)

def parse_rss(xml):
    if not xml: return []
    items = re.findall(r'<item>(.*?)</item>', xml, re.DOTALL)
    out = []
    for item in items:
        def grab(tag):
            m = re.search(f'<{tag}[^>]*>(.*?)</{tag}>', item, re.DOTALL)
            if not m: return ''
            v = m.group(1)
            v = re.sub(r'<!\[CDATA\[|\]\]>', '', v)
            v = re.sub(r'<.*?>', '', v)
            return v.strip()
        out.append({
            'title': grab('title'),
            'link': grab('link'),
            'description': grab('description'),
            'pubDate': grab('pubDate') or grab('dc:date'),
        })
    return out

def parse_pub_date(s, link):
    """优先 RSS pub_date，fallback 从 URL 抽日期"""
    if s:
        try:
            dt = parsedate_to_datetime(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    # 从 URL 抽 /YYYY/MM/DD/
    m = re.search(r'/(\d{4})/(\d{2})/(\d{2})/', link)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                          tzinfo=timezone.utc)
        except Exception:
            pass
    return None

def is_crime(text):
    t = text.lower()
    if any(ex in t for ex in EXCLUDE_KW): return False
    return any(kw in t for kw in CRIME_KW)

def detect_type(text):
    t = text.lower()
    for ctype, kws in CRIME_TYPES.items():
        if any(k in t for k in kws): return ctype
    return 'outros'

def detect_city(title, link, default_city):
    t = title.lower()
    for city in CITY_COORDS.keys():
        if city.lower() in t and city != 'Brasil':
            return city, 'title'
    m = re.search(r'globo\.com/[a-z]{2}/([a-z\-]+)/', link.lower())
    if m:
        path_city = m.group(1).replace('-', ' ').title()
        for city in CITY_COORDS.keys():
            if city.lower() == path_city.lower():
                return city, 'url'
    return default_city, 'default'

def get_coords(city, link):
    if city not in CITY_COORDS or city == 'Brasil':
        return None, None
    lat, lng = CITY_COORDS[city]
    seed = int(hashlib.md5(link.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    jit_lat = (rng.random() - 0.5) * 0.05
    jit_lng = (rng.random() - 0.5) * 0.05
    return round(lat + jit_lat, 6), round(lng + jit_lng, 6)

# ============================================================
# 主流程
# ============================================================
def main():
    print(f"🚀 抓取 {len(RSS_FEEDS)} 个 RSS 源 · {datetime.now().isoformat()}")
    
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=MAX_AGE_DAYS)
    
    all_incidents = []
    seen_links = set()
    feed_stats = {}
    
    # 🚀 并行抓取所有 RSS（20 线程）
    fetched = {}
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(fetch_one_feed, f): f for f in RSS_FEEDS}
        for fut in as_completed(futures):
            feed, xml = fut.result()
            fetched[feed] = xml
    
    # 串行处理（解析 + 去重）
    for feed in RSS_FEEDS:
        source, url, state, default_city = feed
        xml = fetched.get(feed)
        items = parse_rss(xml) if xml else []
        crime_count = 0
        
        for item in items:
            title = item['title']
            link = item['link']
            if not title or not link: continue
            if link in seen_links: continue
            
            text = title + ' ' + item.get('description', '')
            if not is_crime(text): continue
            
            ctype = detect_type(text)
            # 🆕 不再丢弃 outros：匹配 CRIME_KW 但未归类的也保留
            
            pub_dt = parse_pub_date(item['pubDate'], link)
            if pub_dt and pub_dt < cutoff:
                continue
            
            seen_links.add(link)
            
            city, method = detect_city(title, link, default_city)
            lat, lng = get_coords(city, link)
            if lat is None: continue
            
            # 🆕 保留 RSS 自带的 description（清理 HTML 标签 + 实体 + 截断）
            import re as _re
            from html import unescape as _unescape
            desc_raw = item.get('description', '') or ''
            desc_clean = _unescape(desc_raw)                           # 解 HTML 实体 &amp; &lt; &gt; &quot;
            desc_clean = _re.sub(r'<[^>]+>', '', desc_clean)           # 去 HTML 标签
            desc_clean = _re.sub(r'https?://\S+', '', desc_clean)      # 去裸 URL
            desc_clean = _re.sub(r'\s+', ' ', desc_clean).strip()       # 合并空白
            desc_clean = desc_clean[:500]                               # 截 500 字

            # 🆕 用 URL hash 当稳定主键（同一条新闻永远同一编号，跨批次去重）
            import hashlib as _hl
            _stable_id = 'inc_' + _hl.md5((link or title).encode('utf-8')).hexdigest()[:10]

            all_incidents.append({
                'id': _stable_id,
                'title': title[:200],
                'description': desc_clean,                         # 🆕 给 LLM 看的摘要
                'link': link,
                'city': city,
                'state': state if state != 'BR' else '',
                'lat': lat,
                'lng': lng,
                'type': ctype,
                'source': source,
                'pub_date': pub_dt.isoformat() if pub_dt else None,
                'pub_ts': int(pub_dt.timestamp()) if pub_dt else 0,
                'city_method': method,
            })
            crime_count += 1
        
        feed_stats[source] = crime_count
        status = f"✅ {crime_count}" if crime_count > 0 else (f"⚠️  无数据" if xml else f"❌ 抓取失败")
        print(f"  {status:<15s} {source}")
    
    # 按时间倒序
    all_incidents.sort(key=lambda x: x['pub_ts'], reverse=True)
    # 🆕 不重新编号 — 保持 URL hash 主键稳定，确保跨批次编号一致
    
    # 统计
    print(f"\n{'='*60}\n📊 总计: {len(all_incidents)} 条（最近 {MAX_AGE_DAYS} 天）\n{'='*60}")
    
    type_stats = Counter(i['type'] for i in all_incidents)
    city_stats = Counter(i['city'] for i in all_incidents)
    state_stats = Counter(i['state'] for i in all_incidents if i['state'])
    
    # 时效性分布
    age_buckets = {'< 1h': 0, '1-6h': 0, '6-24h': 0, '1-3d': 0, '3-7d': 0}
    for inc in all_incidents:
        if not inc['pub_ts']: continue
        age_h = (now.timestamp() - inc['pub_ts']) / 3600
        if age_h < 1: age_buckets['< 1h'] += 1
        elif age_h < 6: age_buckets['1-6h'] += 1
        elif age_h < 24: age_buckets['6-24h'] += 1
        elif age_h < 72: age_buckets['1-3d'] += 1
        elif age_h < 168: age_buckets['3-7d'] += 1
    
    print("\n⏰ 时效性:")
    for k, v in age_buckets.items():
        print(f"  {k:8s} {v:3d} 条 {'█' * int(v/2)}")
    print("\n📋 类型:")
    for t, n in type_stats.most_common():
        print(f"  {t}: {n}")
    print(f"\n🇧🇷 覆盖 {len(state_stats)} 州 / {len(city_stats)} 城市")
    
    # 输出
    out_path = Path(__file__).parent.parent / 'public' / 'rss_incidents.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(all_incidents, f, ensure_ascii=False, indent=2)
    
    meta_path = Path(__file__).parent.parent / 'public' / 'meta.json'
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump({
            'generated_at': now.isoformat(),
            'total': len(all_incidents),
            'feeds_count': len(RSS_FEEDS),
            'feeds_success': sum(1 for v in feed_stats.values() if v > 0),
            'max_age_days': MAX_AGE_DAYS,
            'type_stats': dict(type_stats),
            'city_stats': dict(city_stats.most_common(20)),
            'state_count': len(state_stats),
            'age_buckets': age_buckets,
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 已写入: {out_path.name} + meta.json")

if __name__ == '__main__':
    main()
