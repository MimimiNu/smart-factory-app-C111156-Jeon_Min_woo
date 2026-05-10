import streamlit as st
import pandas as pd
import plotly.express as px
from pyomo.environ import *

st.set_page_config(
  page_title = "총괄생산계획 웹앱",
  layout='wide'
)

st.title("원예장비 제조업체 총괄생산계획 웹앱")
st.write("수요와 비용 파라미터를 변경하면 Pyomo 최적화를 통해 새로운 총괄생산계획 수립합니다.")

# 1.기본 입력값

st.sidebar.header("기본 파라미터 입력")

months = [1,2,3,4,5,6]

default_demand = [1600,3000,3200,3800,2200,2200]

model_type = st.sidebar.selectbox(
  "최적화 모델 유형",
  ["LP(선형계획법)","IP(정수계획법)"]
)

selling_price = st.sidebar.number_input("판매단가(천원/개)",value=40)
material_cost = st.sidebar.number_input("재료비(천원/개)",value=10)
inventory_cost = st.sidebar.number_input("재료유지비(천원/개/월)",value=2)
backlog_cost = st.sidebar.number_input("부족재고비(천원/개/월)",value=5)

regular_wage = st.sidebar.number_input("정규시간 임금(천원/시간)",value=4)
overtime_wage = st.sidebar.number_input("초과근무 임금(천원/시간)",value=6)

hiring_cost = st.sidebar.number_input("고용비용(천원/인)",value=300)
layoff_cost = st.sidebar.number_input("해고비용(천원/인)",value=500)

work_days = st.sidebar.number_input("월 작업일수",value=20)
work_hours = st.sidebar.number_input("일 작업일수",value=8)
overtime_limit = st.sidebar.number_input("월 초과근무 한도(시간/인)",value=10)

processing_time = st.sidebar.number_input("제품 1개당 작업시간(시간/개)",value=4)

initial_workers = st.sidebar.number_input("초기 고용인원",value=80)
initial_inventory = st.sidebar.number_input("초기 재고",value=1000)
final_inventory_min = st.sidebar.number_input("6개월 말 최소 재고",value=500)

# max_workers = st.sidebar.number_input("최대 고용 가능 인원", value=80)

st.subheader("월별 예상 수요 입력")

demand = []

cols = st.columns(6)

for i, col in enumerate(cols):
  with col:
    d = st.number_input(
      f"{i+1}월 수요",
      value = default_demand[i],
      key=f"demand_{i}"
    )
    demand.append(d)


# 2. Pyomo 최적화 모델

def solve_aggregate_plan(demand,model_type):
  model = ConcreteModel()

  T = range(1,7)
  model.T = Set(initialize = T)

  # 결정변수

  if model_type == "IP(정수계획법)" :
    var_domain = NonNegativeIntegers
  else:
    var_domain = NonNegativeReals


  model.W = Var(model.T, domain = var_domain) # t월의 종업원 수
  model.H = Var(model.T, domain = var_domain) # t월 초에 고용하는 종업원의 수 
  model.L = Var(model.T, domain = var_domain) # t월 초에 해고하는 종업원의 수
  model.P = Var(model.T, domain = var_domain) # t월의 생산량
  model.I = Var(model.T, domain = var_domain) # t월 말의 재고
  model.S = Var(model.T, domain = var_domain) # t월 말의 부족재고
  model.C = Var(model.T, domain = var_domain) # t월에 하청 계약되는 제품의 수
  model.O = Var(model.T, domain = var_domain) # t월 작업된 총 초과시간

  demand_dict = {i+1:demand[i] for i in range(6)}

# 목적함수 : 총비용 최소화
  def cost_rule(m):
    return sum(
      regular_wage * work_hours *work_days *m.W[t]
      + overtime_wage * m.O[t]
      + hiring_cost * m.H[t]
      + layoff_cost * m.L[t]
      + inventory_cost * m.I[t]
      + backlog_cost * m.S[t]
      + material_cost * m.P[t]
      + 30* m.C[t]
      for t in m.T

    )
  
  model.Cost = Objective(rule = cost_rule,sense=minimize)


# 고용인원 균형

  def workforce_balance_rule(m,t):
    if t==1:
      return m.W[t] == initial_workers + m.H[t] - m.L[t]
    else:
      return m.W[t] == m.W[t-1] + m.H[t] - m.L[t]

  model.WorkforceBalance = Constraint(model.T, rule=workforce_balance_rule)


  # 생산능력 제약
  def production_capacity_rule(m,t):
    regular_capacity = (work_hours * work_days /processing_time) * m.W[t]
    overtime_capacity = m.O[t] / processing_time
    return m.P[t] <= regular_capacity + overtime_capacity
  
  model.ProductionCapacity = Constraint(model.T,rule=production_capacity_rule)


  # 초과근무 제약
  def overtime_rule(m,t):
    return m.O[t] <= overtime_limit * m.W[t]
  
  model.OvertimeLimit = Constraint(model.T,rule=overtime_rule)

  # def max_workers_rule(m,t):
  #  return m.W[t] <= max_workers
  
  #model.MaxWorkers = Constraint(model.T,rule=max_workers_rule)

  # 재고 균형제약
  def inventory_balance_rule(m,t):
    if t == 1:
      return m.I[t] == initial_inventory + m.P[t] -demand_dict[t] + m.S[t] + m.C[t]
    else:
      return m.I[t] == m.I[t-1] -m.S[t-1] +m.P[t] - demand_dict[t] + m.S[t] + m.C[t]
    
  model.InventoryBalance = Constraint(model.T,rule=inventory_balance_rule)


  # 최종 재고 조건
  model.FinalInevntory = Constraint(expr = model.I[6] >= final_inventory_min)
  model.FinalBacklog = Constraint(expr = model.S[6] == 0)

  # Solver
  solver = SolverFactory("appsi_highs")
  result = solver.solve(model)

  rows = []

  for t in model.T :
    rows.append({
      "월" :t,
      "수요":demand_dict[t],
      "생산량": round(value(model.P[t]), 2),
      "재고": round(value(model.I[t]), 2),
      "부족재고": round(value(model.S[t]), 2),
      "고용인원": round(value(model.W[t]), 2),
      "신규고용": round(value(model.H[t]), 2),
      "해고": round(value(model.L[t]), 2),
      "초과근무시간": round(value(model.O[t]), 2),
      "하청량" : round(value(model.C[t]),2)
    })

  df = pd.DataFrame(rows)
  total_cost = value(model.Cost)

  return df,total_cost


# 실행 버튼

if st.button("총괄생산계획 최적화 실행"):
  df, total_cost = solve_aggregate_plan(demand,model_type)

  st.success("최적화가 완료되었습니다.")

  #st.metric("총 비용",f"{total_cost:0f} 천원")
  st.metric("총비용", f"{total_cost * 1000:,.0f} 원")

  st.subheader("최적화 결과표")
  st.dataframe(df.set_index('월'),use_container_width=True)


  # 시각화하기

  st.subheader("수요 vs 생산량")

  df_melt = df.melt(
    id_vars = "월",
    value_vars=["수요","생산량"],
    var_name = "구분",
    value_name = "수량"
  )

  fig1 = px.line(
    df_melt,
    x='월',
    y='수량',
    color="구분",
    markers=True,
    title="월별 수요와 생산량 비교"
  )

  st.plotly_chart(fig1, use_container_width=True)

  st.subheader("재고 및 부족 재고 변화")

  df_inventory = df.melt(
    id_vars = "월",
    value_vars=["재고","부족재고"],
    var_name = "구분",
    value_name="수량"
  )

  fig2 = px.bar(
    df_inventory,
    x="월",
    y="수량",
    color="구분",
    barmode="group",
    title="월별 재고 및 부족 재고"
  )

  st.plotly_chart(fig2, use_container_width=True)

  st.subheader("인력 변화")

  df_worker = df.melt(
    id_vars="월",
    value_vars=["고용인원","신규고용","해고"],
    var_name="구분",
    value_name="인원"
  )

  fig3 = px.line(
    df_worker,
    x="월",
    y="인원",
    color='구분',
    markers=True,
    title="월별 고용인원 변화"
  )

  st.plotly_chart(fig3,use_container_width=True)

  st.subheader("초과근무시간")

  fig4 = px.bar(
    df,
    x="월",
    y="초과근무시간",
    title="월별 초과근무시간"
  )

  fig4.update_yaxes(range=[0,max(1,df["초과근무시간"].max()*1.2)])

  st.plotly_chart(fig4, use_container_width=True)

  st.subheader("자체생산 vs 하청생산")

  df_prod = df.melt(
    id_vars ="월",
    value_vars=["생산량","하청량"],
    var_name = "구분",
    value_name="수량"
  )

  fig5 = px.bar(
    df_prod,
    x ="월",
    y="수량",
    color="구분",
    barmode="group",
    title="월별 자체생산 및 하청생산"
  )

  st.plotly_chart(fig5,use_container_width=True)

  st.subheader("비용 구성 대시보드")

  cost_columns = [
    "정규근무비용",
    "초과근무비용",
    "고용비용",
    "해고비용",
    "재고유지비용",
    "부족재고비용",
    "재료비",
    "하청비용"
  ]

  cost_summary = df[cost_columns].sum().reset_index()
  cost_summary.columns = ["비용항목","비용"]

  cost_summary["비용"] = cost_summary["비용"] *1000

  fig_cost = px.bar(
    cost_summary,
    x = "비용항목",
    y="비용",
    text="비용",
    title="총비용 구성"
  )

  fig_cost.update_traces(
    texttemplate = "%{text:,.0f}원",
    textposition="outside"
  )

  fig_cost.update_layout(
    yaxis_title="비용(원)",
    xaxis_title="비용 항목"
  )

  st.plotly_chart(fig_cost, use_container_width=True)



  st.subheader("월별 비용 변화")

  df_monthly_cost = df.copy()
  df_monthly_cost["총월별비용"] = df_monthly_cost[cost_columns].sum(axis=1) * 1000

  fig_monthly_cost = px.line(
    df_monthly_cost,
    x="월",
    y="총월별비용",
    markers=True,
    title="월별 총비용 변화")
  
  fig_monthly_cost.update_layout(
    yaxis_title="비용(원)",
    xaxis_title="월")
  
  st.plotly_chart(fig_monthly_cost, use_container_width=True)

else:
  st.info("왼쪽에서 파라미터를 입력한 뒤, 최적화 실행 버튼을 누르세요.")

