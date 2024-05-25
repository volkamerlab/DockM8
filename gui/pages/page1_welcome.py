import streamlit as st


def app():
	st.columns(3)[1].image(image="./media/DockM8_white_vertical.png")

	st.markdown("<h1 style='text-align: center;'>Welcome to DockM8!</h1>", unsafe_allow_html=True)

	st.markdown("<h2 style='text-align: center;'>Choose a mode:</h2>", unsafe_allow_html=True)
	col1, col2 = st.columns(2)
	with col1:
		st.button("**Guided Mode**", type="primary", use_container_width=True)
	with col2:
		if st.button("**Advanced mode**", type="primary", use_container_width=True):
			st.switch_page("./pages/page2_library_analysis.py")
