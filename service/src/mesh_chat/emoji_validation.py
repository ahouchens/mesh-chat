from __future__ import annotations

import base64
import hashlib
import zlib


# Pinned official data makes acceptance identical in frozen Windows builds,
# Chaquopy Android, and every supported Python runtime. Only entries whose
# status is "fully-qualified" are present; component, minimally-qualified,
# and unqualified rows are intentionally excluded.
UNICODE_EMOJI_VERSION = "18.0"
UNICODE_EMOJI_SOURCE_URL = (
    "https://www.unicode.org/Public/18.0.0/emoji/emoji-test.txt"
)
UNICODE_EMOJI_SOURCE_SHA256 = (
    "8f3735cda1f92a779d78af67cf86066bb1f07143dc22f2ac29394d9bc57ab21a"
)
UNICODE_LICENSE_URL = "https://www.unicode.org/license.txt"
UNICODE_LICENSE_NOTICE = """UNICODE LICENSE V3

COPYRIGHT AND PERMISSION NOTICE

Copyright © 1991-2026 Unicode, Inc.

NOTICE TO USER: Carefully read the following legal agreement. BY
DOWNLOADING, INSTALLING, COPYING OR OTHERWISE USING DATA FILES, AND/OR
SOFTWARE, YOU UNEQUIVOCALLY ACCEPT, AND AGREE TO BE BOUND BY, ALL OF THE
TERMS AND CONDITIONS OF THIS AGREEMENT. IF YOU DO NOT AGREE, DO NOT
DOWNLOAD, INSTALL, COPY, DISTRIBUTE OR USE THE DATA FILES OR SOFTWARE.
Permission is hereby granted, free of charge, to any person obtaining a
copy of data files and any associated documentation (the "Data Files") or
software and any associated documentation (the "Software") to deal in the
Data Files or Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, and/or sell
copies of the Data Files or Software, and to permit persons to whom the
Data Files or Software are furnished to do so, provided that either (a)
this copyright and permission notice appear with all copies of the Data
Files or Software, or (b) this copyright and permission notice appear in
associated Documentation.
THE DATA FILES AND SOFTWARE ARE PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT OF
THIRD PARTY RIGHTS.
IN NO EVENT SHALL THE COPYRIGHT HOLDER OR HOLDERS INCLUDED IN THIS NOTICE
BE LIABLE FOR ANY CLAIM, OR ANY SPECIAL INDIRECT OR CONSEQUENTIAL DAMAGES,
OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS,
WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION,
ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THE DATA
FILES OR SOFTWARE.
Except as contained in this notice, the name of a copyright holder shall
not be used in advertising or otherwise to promote the sale, use or other
dealings in these Data Files or Software without prior written
authorization of the copyright holder."""
REACTION_EMOJI_CATALOG_SHA256 = (
    "d4f4b496cf4a6f621575353540a4f778f3461535aeebb62de408369bd40608f9"
)
REACTION_EMOJI_CATALOG_SIZE = 3963

# The complete 18.0 catalog currently tops out at 10 code points / 35 UTF-8
# bytes. These independent transport/storage limits leave headroom while
# rejecting pathological input before a membership lookup.
MAX_REACTION_EMOJI_CODEPOINTS = 16
MAX_REACTION_EMOJI_UTF8_BYTES = 64

LEGACY_REACTION_EMOJIS = ("👍", "❤️", "😂", "😮", "😢", "🎉")


_COMPRESSED_FULLY_QUALIFIED = (
    "c-oD9*>>B!(&c?#qwo5vhrg${Qyj-m98nah!5ZxN`@c}4D9MxL#8%8<t^ZMS9-z-!{Q}Kh!nR42z@rO+AV8q1c2!{_K>hP()cWwx"
    "o6#o(rwBeGI79Hc45A;1os_{?0z9|+3&9E*UlCj&I4^_Q17aSEC5Vj>Tz>d7`u%@je8eXR#&~jr*f#`I1Xn1tMC=-|0Kp}KTafx2"
    "0T_uuH0tB_-x2E~SfChUBNQ9`Lhejre_Gx@Z`vzET!Iinh@5K#ck)PxDk79wEkx2X_0L&<U(VbOOf78$;9vxHqX@AlloW}dkp>#k"
    "009_}?hwQf`X>VLH$#chPYL!Mh+y{!0Pbvy;05^|r1i=m77<bHN{HTow~r;bJHr|1j8Mf$z(o}+@HqR8V289h0<ba?&_rDV6&M`>"
    ">(L{EAp+6-cLX3m68XU9Odb&)po9?^js(pwWe^l)5VlIb{@U{uqF{t41Mm=lo8T2eh9F0-&_l*ZWENiW$S6gC=f+~CsC$GGV~`rd"
    "`o^%n5LyXgZXxU^M13LbCj{#ugb0CLc=O@U^$){Wzl=v^TollsRqv9WxhtPbpwk%qhcML;HXOo+6X-7#%Y~ALKqP^7BX~dv;|`&Y"
    "P|R0iz*<xtLK9+kgRNl)2nHX?!R2C~{C2%Jk3mTxNCn>{_~(uP%1Fvc#z@Wxkc%b~m=Y368Oa#Q89|9*cTaWLHH9RSGLkWpGg5r`"
    "bM*~Bd47LQ%{4RE++2mgPy*IIWbH%NK4k4fQ)2Zffhi%8l#z^)oDnIpk$@#OEU{sU4NGiTLVRb-5?hwovc#4pwk#n{z!OV6vBVQg"
    "Jh8+ROFT=!63;C0%o5Km@yrr060pPzOT4he3roD15<y!6nn;@_(x!>DX(DZ!NLvD$2unmP5wS${R>GHnC483fS;A)t-`GbRHdS7X"
    "iL{N0w2g_hjfuPw_$~nnd?$hLB=DUCz7wbi2?*2!fqEcN4+QFgG;SmyjT_RqA&nc-xM7Kr1S~OPi4jYTSYpHyV+mMd%o1ak7_-Ef"
    ">XY{L3)T09>ia_VeWCiku*6phSmG;7d}WEREb)~k&Lm)oGnP1Gi8GcsqstB?pvw;EvIDy8fG#^AjdKY|<D4|kN#mR}&i5uVx)u`|"
    "UGGgquBo|Z=9-(UDEy}cRQOLS{3jLulM4SymOKf_l1G+2vgDB^k0m-1utbL?IxNv)i4M8iNkFc4<Z4H*cI0Zu62B#2iQg>on<aj;"
    "#BbwE7x)=Rx-gD(VI1kgIMM|rxR8JnTu_1wN^n65SR$HAK$D%)WT!OQDNT0D64D)BvBVWiT(QIzOI(pFUjlN)_9I~X5wQITd{biF"
    "mcW!4vyB?FjT*C!8nX#m$(ZmLas5SHe-YPT#Pt`s>PkSa*y{!C^#b;KL6?$mB%tK%Wg_-65qp`4y-XxS-D{S(W{GQ-xMqnrJC|-x"
    "#s}}+n3a|tNXrkTz15e#r@bCX%MPUF2h!f^%MR3+9pE`TP+xYSzWhLa`GNZK13c#k>MIV^R~)FXI8a|v=Xosi1KRGGwmYWnj{Ua>"
    "jlX*PzRxo*>lv5zjLUk)W!dP2pCvE^B$6_cF_JSPMzxiIM#Z5^#Gy;Xp-aS}OSqJPG?t{XB#k9$EKP|y?&cEvDS;_FXTv*Z!#iig"
    "J7>c?|0MxS&=u!&#W`JZ{^p7&63`V-=!z$F#S^;X328{xucYxx8n2}BN*b@E@ks*G_(U3?NaGV}d@?0snFC`|vciOUj?vs4gTSE0"
    "aXhZjUx4Z63IqP&mjon3;R6aEQ22nt$DstKghWzCGDdPnL=+)3CyhC2%t>QT8grJ2C18n|C1RF{St2G^fdu3#AXfpo3dmJJ8jli?"
    "21o4yN9_Se?Ey#a!9oI-Sg^!`B^E5PAXj|}$W@<Q^~qJAT=m~dU}`@;*(+;bRHdXUB~vN6N-63oa@SIHT8d6f(P=3<Ek(zq1Pf`O"
    "<_~YsS@)@RpIP_0bzfBP_wh%o?nkTcN2~5ftL{gu?#D{qTdVG^Rrl7adu!Fbwd&qh>fTs&Z>+jER^1z`?u}Kq+$R#yMibg-LK{tJ"
    "qY14#sUVtI8cHk;C6<N~OG8OrLvc`z*X!Q<sCA!N_qlan)qYaZR$^&Cv9zC9+D|O)Cw1+U??;R8M~m-Ai|<E^??;R8#|qzDi|?()"
    "_txTjYw^9c_}*6d-dcQbExxxF-&>3Ct;P4Y!uQ7Fdt>pvvH0Ftd~YniHx<4&7T+6-?~TRx#^QTp@h!9-Ywgja-O>e*c1ssL+AUr1"
    "Xt#91qiX3MtL<xr&WWOPqUf9`Iwy(_TW(o-?Xgeku}|r-PwBBw>CwYw5Wtn7fGa@(SAqhr1O;3P3Vuq!5*$PY97F{iL<Jl~jXeoC"
    "?&R!s%-QRhv)8frR-!7^zNkt`RZ6B(a+OllQ>t33&}k_;Ek&oL=(H3argS7A0-TMHIU65yHa_NTeB7z=*-;2|6apQEKu00aQ3!PE"
    "d@2Mw3W1J7pra7zC<H!BKm<577;|bc=G0)!sloVjjnB^tfzJwo&kBLh3W3iGfzNe56#}0X0-qHEpA`b16#{1x5CJY-jk$C+=F-)e"
    "OIPEw8lPthfis1`nL^-9A#kP;IIHui5I9o^oGAp(6ar^90^vsqICcBTsoO_R-9B>a_K}mlk5xYRMO8|wQZkj2tCXUiQs>h~phBmm"
    "=(H4_mZC#UzDYnE;7gD(UxJMJ5@gIb4&!e%O?^`~@J-pkH)R9glns1SHt?;^r?P=>$_BnE8~CPd;G2y=ybstzaSbBo8br)Bh?whV"
    "v0v-qd^PLw)vU)?vmRf~dVJM)`gK0ltjAZg9$(FRd^PLwl?|LrKpWul@|erZV=ga`&uIhaHBFr>8#q@saIS3NT-m_6vVrqDpUMW#"
    "l?|LL8#q@saBd?I%_ZQX59j<5=ll`p{1NB;(Y(s%zNkt`RZ6B(a+OllQ|f%$2vq2_6rGl$(^7PpA}`+gHZ9`Yw1{uhBEC(F_%<zi"
    "uJQS-5O`JyJSzmA6#~x+f#*7(3V~;Zz_UW&St0PO+5wE}|4atFBb{1Gs!}qQlB<-Wnj-V*%AHN;ZBAWJ$y7?NQtEV)`kkVaC_0Iv"
    "lPEfgO~=fJI=%XA=>0ym?lbE?x9*Ggd$aan;`O>KYY*@DnRTCA_tm<SYTT+jvFc8&x)ZDJq+Ykd#9!4hdB0Ds`^>t}t^4Br-e6+l"
    "^|~vVyx(WmeQw=X>rSe1tM0_AJF)6cth$qW-NwI$%D;xnzlO@chRVN&%D;v+{~9X)8Y=%9D*qZP{~9X)8rJ-4sQhcF{A;NEYpDEd"
    "sQhbK^RISZx25;{)Vj~C``o%O-tUbqwez|yz2B$SeP-R~)_t|^q#C#CPOQ2UtM0_AJE_-gF!8LFBhOkn@~o93&ssV1td%3Lvfk-g"
    "YpI^Kmg-q+sh+i#>RD^4US(CvvsTkQYc<WYR?|FdHO;eD)4a-RT0gF1@_wIM_nCE{TldBLy}`u9>vdN!dB4xB``o&()}2)2R^5qJ"
    "cVg9@Sam1$y4eojTJ7+y)ehfU?eMMD4&Pes@NK0XzO~xnTdN(uwc6oZs~x_z+Tq(uJA7-k!?#vDd~3DCw^loRYqi6-@0f&X9h3L_"
    ")Vj~C``o%O-tP@2VOq!J{XVtsGwVLL?yGet)wor6V%42kbthKcNxg3R&f4;wwdFf&%Xik6@2oA~Syy~#ZTZgH@}0HiJ8R2#)|T(A"
    "E55U~d}nR>&f4;wwdFf&%XiilJ9)M2<khm1SIbUbEjxL&?Bum#C$E;ByjphhYT3!FWhbweoxE1;<khm1SIbUbEjxL&?Bvz5lh?{v"
    "H?qdMku}zhtg&unjddeytQ%Fvx{)>3jjXY5WQ}zrYpfetW8J7S){U&OZe)#hBWtW1S!3PE8tX<COcoX<3k#Elg~`IgWMN^ls9>_N"
    "Fj-ibEG$eG7A6Y|lSKuSg@wt&!en7#vam2&SePu{#=2Ku?6GbwB~>YzO3779QBB#8b>Hu7I`3oMT1uu;a+Ol2lhp4NokY<|6rDuT"
    "No+dCmL{#bExq5T)_rE(=hl7kes65a#OrleZ0Y?zv+i^2zFK!ujazjmR^5qJcVg9@)axcDp@m6kVG>%Hgcc^Dg-KY!B(yLIElffS"
    "lhDE>v@i)Pn1mK4p@m6kVG>%Hgcc@pe<uOo_}%f1-yPrh-SLgz9p4e&)!tLysrQ|C>V4;(df$1c-gn;Ft5t?hOVMd5IxR(~rRcO2"
    "9g{Nn$*Tcjz}KDwzV;mOwda7ZJ*7~U+kI)3lB$$UrQ|B5sHc!rOOa|RQY}TQrAW0DDZbP=k$^98xW6sr{<e_&+d}Sd3r}jVT29nU"
    "oD=mD=S024IZ-chPSi`BlRBU3CC-U@iF2Y};+&|LI43p&vu6nm0y8e&&bW9x<Kpd%i?_kE1au&l2v{OuiQv6N&CJzuZ=jZY1GU^6"
    "sO8>3E%yes<=#Lo_XcXYH&DyHfm-ej)N=3Yvjp74%GbXuzW!bD_3!F!XXujzTq5VjgoqmxB5q8G-Zmz@NI;Z%;3VLIlYj?Kg0}-F"
    "GPCFI(}25A1MWTzxcfBNzLlt<w^e%CD!pu#UbadvTcww64bQF8%U0=StMsx}dfBRtDY6TOn~MYPC=R%dIN;vlfSZ!zfdqVk$MY01"
    "&r`%aPZ9GxMf6hwYLYEy#FjH+%NhNAD^YtTp_<J|HJg!YHY3$+MylB~bXtl|OVMd5IxR(~rRWf4*^|Z-J^@eo1U%sr@Ptpm6F$L1"
    "%^Dt*ojoW!dr)@vpzQ2H+1W##Pi1Eh%FZ5?ojoW!dr&XD9weX*5P^sYL_{DW0xLPX%RSC3?r~mmkMoLqoLAiAypoN}rz~;G5~nP2"
    "$`YrvvquTY6}S0D+~yl`n{V`3-w^3p%Oak&EaF+qBA&G@;#tcgUS&DQvzBu_YdOcWmUBF7Imfe>bG*uui)SrEdDb$NXDvf{)-sf5"
    "Eko^T?E_kOO6yK(-6^d*H7IsIOJGWL*c)`%8+6zkbl!RcIjG95=n=P~N8E}YaVvWCwiVq>luxaR@~JgZKD8#wr`AOI)S4*ce*Pi>"
    "ckHvLnX{*vv!|J}r<uQ0y>4GrrKBn)Qz^MhDe5UzudC2$DLO4hr={q$6dk7QBp?DjEH>w1u{jTm&3RaCzN_)MQwZ!70y~AkP9d;U"
    "2<+;7Dg<^4ft^BNrx4hw7uaJ7*bnl2WX$uCG0#WFJRcd4Yuio6Y9q^7ZDbj%jVxoek!7qlvW)9|s*NmTwUK44HnNP>MwYQcU?Kq#"
    ";Q8#B=d)v;&yIOMJD$||oG1h)3W142V4@J1C<G>TJ{1BJg}_81Fi{9h6arHThyV{9#yoHs^T1)u1Bdan#^+QaFjWXl6#`R*z*HeH"
    "t@Ei6m?{LO3W2FYV5$(fl7I;C0A<Vrlraxb#ymh7U)A`$QV3ir1g;bUR|<hEg}_yvPldphLf}dvaHSBqQV3j2Km>R!GUl<!n8zYx"
    "9*c~xYkXcS1g;eV*9w7ag}}8!;JVJILf~2<aIFxyRtQ`x1inj9BmKShz>Ng82X1N);E3!B$H&7n3AnnzO|l_3$%fn{8*-CuSlc8U"
    "s!g(?+9VsQO|qfdBpa$tvSDqLY^XNLhH8^+s5Z%lYLjfJH_4t$Km@owFy!{YklO=8ZVwD=+XF+jJup<;14FevFjU(EL$y6HJg@Vq"
    "5K!9#L$y6HRNDhXwLNh1O9F$ygk!x4$9fZv^(GwaO@3AR+!s|TsY=OIO0H6hdP<#78-WU)mZH;AbXtl|t4inlzuR<bDXB`yR7$Q="
    "ih9Z$)x!i2XQl3}%$=3HvkFJn8}<(FPTbs`xVbxVb9dtA&d!QG3E1xQP)p21Ein(Z#5~jz*ABJB>QGCp4z<MUP)n>1wZ!UBOI$nD"
    "601Wku{zWet3xfZI@A)YLoIPf0wTaeEin(Z#5~jz^H57%JJb@ZLoKm7)Do*hEwMV(601Wkai`9wLO>mAiPfQ&SRHDKI~swSMRaUG"
    "eWz1P$y7?NQi^)YK?kt}J52d-R_4yi-C2br>#&1#oPKKQ*}>h3o4XS?cPh&qAH27Y58hkH2k))pgZI|)!F%iY;C;33I>8DNm65tK"
    "GFL|K$|w$G@c8h(b$s~VIzD`F9Us28jt}2k$A|B$b=L_xq^(g?8JR01cV!%uHmPuzSkfkzw238cVo94=(k2H9x};59(k3ox6PL7!"
    "Lt0v!wT3sh*6`-m8s6Mm!<$=cc=NPcx66`KmnEkzOHN&uoVqMIJ!Hw&YUtcr4V_!7p>u0BbZ)JN&eLk$E=x{bmYljQIdxfb>ayhY"
    "kR@B|%5!U7d2X#M&#iUkxwWo5PpfsiEID;qa_X|=)Md%3%aYSWmYi8emRYuyStgZPmXuirlvV3?S#svG<jiHsnah$hmnCP1EIG4`"
    "EVFDYvrH<pEGe@LD67`(vgFKV$(hTNGnXZ2E=$f1S#o9>S!UT*W|>rGSyE;hP*$zmWyzV#k~5bjXD&<5T$WtR@IOgl#=t(`Qu%yK"
    "<?}6-&$m?mr|L*`UsR=}DkW1Xxk@SODb<l`g-%P+X(>7_MW?0cw5oL8@vz6h?{sP@nM%o3N>NWaIQX;#J52d-R_4yi-C2br>)_zi"
    "Qm=!%6E}A!ZthOp+&RX;iS?<K#QM}qVtr~Qu|BnuSf5&v`|y(lT(6=Bg!F)r9uU$42EQfXPAYyjaKO(74*1!?!Ecs$GP{wu9b~}m"
    "AOmg(8E`wu;B7mIjN<P3TJoN+CGYuK@}93H@83$)UX9<Ym+trKrTe{l>3*+Xy5Fmp?)SBq<@f5P`@MSUey?7-->aAI_xg<Go2t7H"
    "a;bm&N@r#6tlXVd)Xk`x_3F;b+*!FhtEijkL0Xwx<jhSgbJNP*v~oAC+%0nMrd7CU6>eIEn^tj9<jNSqWYxb}rn544RzrnFeb`aW"
    "dUa=I?yTIMRn$i^2We$)kux`~%uOqI)5_hna<|C2n^xhbRk&#tZd%1*krSoL+PA`VR_4xXsIaIH(yCdn?ySt6mAkWw`nc~Pt;{WQ"
    "=BAaoY2|KOxtmt*7CCp*D%`XRH?6`=t2iifJd}XV62E{R^9$(l@a;jiYQx&n>`*QG4%MRXP%Zin)uQiEE&2{?ecw<m`VQ5i?@%rJ"
    "4%MRXQ1z;p5)gq)B5+9rE{VV;5xA`Jd8rV%R0v!u1TGZ<mkNQ)I-d%GONGFtLf}#%aH%%)VF2f!OTd{A-&6X0PwDeLrEk8HJ$*Lg"
    ")DsC<kQ>N-ZXox$f!yZ?a=&d#@*~PVKcejOBg#HMqU^V;g=!O`wwh|S)l{pkrdn+^)oQD$R@>TrUm?{}q*{tpOOa|RQcO9OfH-iE"
    "qt88#KKD5K+~eq<)>u7NAe<@?P8A5J3WQSy!fBmPg}|vo;8Y=Sst`C;??!(}z_-Ic_;&aQ-wyxa+u<L4JN%>e4)=$8JN!ev9sZ%-"
    "4*yVZhkvNI!$0bLs<*>G)Z5`7>h16k^>+A&vVjW;XaoE(y3Y@z`}{Dv&kv*f7d1^?C>yv?HgKVA;6mBJg|dN*I-kl0E|d*iC>yv?"
    "HgHi#;LmhtF8j|?PxreI_t(r^b8{`s<L_*ma&|&$CuDX)ZYLDAgjyR=CDO8qv}__Rn@GzhLMXoRO6~I#Vm?11=JOL`K0hHQg=%V2"
    "UlH@wSHyhv6)|6ZMa)-U5ql@qQlwgnR7;U+DN-#(ihl7V0owsC2u!#jFyVs0gbM<br<%7usdnH=wF6J89e7ghz>{hRp6Yz6cHl|1"
    "15c_Qcv9`alS1I91Vn)6DkeNvG2yw23C~qbYUe5@>RiP{ovWCra}^VHu41CjRZM=?`BVs~a}^VHu41CjRZP^mis(fG?h5BV?1=lY"
    "BkseFxDPw3?Zb}LKI};C!;aKG>`3jyj?_Nv=%vo5I$5IjVMl5ocBJ-UM`|B-B=U0aeZ;-@5%=Cl+<PB!?|oF4E>#Gm3V~E1kSYXH"
    "g+N`pR3VTm1X6`Sst`yU7P(gU&PA?jR_4yi-C5QmS2gR^ot3$>a(9-s$aRob<`y|~)5_emayPBqO)GbcoV#fiZd!$#R^g^q92B{-"
    "CS|e?Epk<}GIv%(h1MchHS5)#mASKWcb2utb&yu(7CCd%%G|VaH?7=FD|d^WyJ;0}T7{cd;igp_7CBL>Jg~@B&C1+a4Ha68T-B^s"
    "cUI=k%H3JkBG*A$nOo${O)GQL%H6bbH?7<)a_**8xM>w`T7{cdaZuz)y3UNfYQ|nQW3QUMJ;+|Q-alrlSItzfnyFqjQ@v`YdewUW"
    "n5kYhQ@v`Ydeuzzs+k&Bh;%s-$caEs1acyf6M;JCxk4aU2;>TZTp^Gv1nQjU3V~c9kShdog+Q(l*hxSHc)~5>3AczR+#;TEi)ts_"
    "B6Y$oQYYLZb;2!DC)^@+!Y$g>`BVs~6K;_@;TEYAZjnCWHj;pyGygL%=6?pp{LjFc{}~vMYRi!$wa__I3!Nji&^b~Iog=l-IjZxi"
    "7CJ|2p>w1bI!9`ub7UhhZAoAdkVwi%#z@Wx5SX?lU<s~MPPtAw<vQiGT|cK9U7MjxeFXZJTpc3mtkj*AxwCS2mNnWv$VTdBBXzTp"
    "y4gtGY-DaWGB+EUn~luPM&@QCce9bZ*~r~&<Zd={HyeeUjl#`F;bx<7vr!ymBam+$-c~!{nh_luOI5QncUJDsvc^)?tXJ}rx}VA1"
    "S-CsQ8dNEwhqF@hlewSC-C5S?>LAhF4S0T7_S-7a+)cD_6D{0C3pe1!VcBm<RK8%ma$D2FZA}ZeH7(rMv~XL~+l*u7wx)&Knig(r"
    "TDYxg;kKqX*;j6BTDYxg;kKrQ+nN?`YkHG?<+i4U+nN?`Yg)LiY2mh}H`!MtD&N;!S0|1RYg)LiY2mh}h1;4IZfjasiKcF%sheo("
    "ChD-Jh1;6eRic@jXyzuGyNTv*z#Z1Kt`g1NL<=|3!cDYr1MaY<HBZ;dAyxiiNytAe3HgU5A^)%>^s8O8j7P7d{p*l2^P6L^=6EJM"
    ";+g!2XKLd($1|@-Jd+*qOn$^OwE^9~;wL)-!|VutvLpD(kKiXif}i{d4D%!SDURT$ID((z2!4uY4ELWSRrx{fQ?7^d?f%^HOnSsK"
    "*%8m=M?6#O^Zymk=@C4qNAR2;!E<^9&)E??XGidy9l>*U1kc$KJm*L7oFBn+egx0?5j^Kd@LU|hb8!UE#SuIgNAO(y3!WDZ{<%29"
    "KNm;%=i&(eTpZz_izEDVafE*^j_}XL5&pS2!ao;B_~+sX|6Cm5pNk{>b8&=!E{^ce#S#9wIKn>{NBHOB2>)Ch;h&2m{Bv=He=d&j"
    "&&3h`xj4c<9sOtWFZ!$Gi2gG<qW?^e=s%Mq`p@Ku{xdnE|4fePKa(T+&*X^yGdZIFOpfS3lOy`i<cR(=Iimkej_5y=Bl^$ei2gG<"
    "qW?^e=s%Mq`p@Ku{xdnE|4fePKa(T+Px2fF5^#pc;d96_a>#*j7&OfA8mD%RbGpXKT;nXRar)LcZ)=>eHO|x;r)Z6Hv&KnT<7}*P"
    "8rC@fYMgjA&bS(<T8(q8#>tg)R^^;dHO`|NCs2(ur^YE$<6Nn6lGHdmYMd4|&W9Q&LX9(^#;H%^oTqWJ(>Tj%oZd9fYZ@msjWe0X"
    "DNN(srE${II9q9)ra0#(&WTCmjHGcY(l`fcoP0FSIvS@Njq{Ag2}a}0qH#*mIG1RgL^RGG8mA47^M%HVLgNgfaca;wCup1uG|mDV"
    "hyRV^{>A~nbENMa;x~@%8wd4`qxr^ReB=1Nap2xKVs9L(H;&O82j`8W^2XtK<2bx=0NyzAZX9wqj<p*H*^Q&?#$k2ic)D>Q-8h17"
    "96G-<v@rMk%UmbL2a=o*&)wDN+7|lZh4ZP{`S9FbO{KO(%b9376Q`VsQ_kdH$yw#>0JGIc4@h}Hh$`6woKzn@AVQ_W%OB>G6Y>vr"
    "Gkm-khdP7h`+g=~!UIV<rxt%t3UJnMg--%^an_}av^l=JIR_VAd?&VxzayF7No@ap9vn{XqT%f#HpgMPIlj@{#h*QNzeoV9UgP84"
    "^N+a4mqNPuPlB${!pWi)K5n^!kX^*)^4Wj<+4LMcyyket+!d-2yo+z3bn!?R|Mb(v8R;&L33uUTU8x0=%x)I}Q0ijG!yKQGpF^lF"
    "w%W}h?OeV#57xTaV$&7=unnz?{fJ$Baixosx81^gm|iOCBaq}*3B+qp_fK>&-0I5L`Jt&fbUH`cT!{WVa^*|?A_QvcLe4I@=|aI>"
    "6zif`7qAa53}pZ|2VnER5qw2}=a<mS92%J83-NP&B77-8%-?Wd7QFxGO<(HAQJyZ8)s@-+dKaqh;vZ_dQn{#Fu*LuObiW~hB35D&"
    "0vEnC-Teyz<eH1NfpQm|EJ0%_NC43}zFR$qO6E|`T=XK^Ma?V3x}pdO(1i&tg%>FX?JmK_z#MBHyck$u5OeUcgtC^fx;Z!sL8%QE"
    "LKw~xmg1ZL6>CGeGceVL(YB$*HW+Q=sioYaq9shT4KCWC-IiOphWt-+yZG>DG}_nbp)wEF<AEU$%3XrW5(GTh>Jnu<Sd9mqJYeiW"
    "1Ku|YL^(ImqX#TJpgaT09+cw=70BcPJr8E=!Ejbcn*lCQ{`3hMGpKkb&%t13u(BD{*@j)Tf0;jt!UHorze4dDbUTCH#quW{sBH#a"
    "tYElppu2)vS5uK_&o10yg@-(-X(qhDWL98p2D6{R+h_94a>yPFP<X_HPG^vJhKD^c=|Pd6a0<z1u#q;@*G4TXkwg9nLc{_$^6$_y"
    "aOgo#E0mqVmu9HmljR1$9YZZMu<Jpyo|HgUp41{Ti5!9?49J6Hc&N&Qn|XpMc=2HCGjKY?b2Hp}z|DiddJx(ZHG=z&n1g)D3Dz-_"
    "M}!T)?TLP+QV1yj?=qW~W(6@;f)dQlgNu7&KQK@aR_(#MJh3kMUo??V{=`Rcl|L_qVZ}&`VQevsZ6;D>#%f{EGibXHURS`w7mtAP"
    "wPAN{@fYaz^7p>brK~A|algMmH~V0=?~0v(=B1pK9hkGE=C9uUD|5Xz*YD<fW3E$ky)^rS#RGxn5*SQ@hHu=>pO`BY;6njE<no~{"
    "AENuvmJg-)sKJLme8}hndmq@#|3&+N-Iot*!4WQ@fJ+=|#<K(2T?|zWyfP^<Ezh?yzA1kK6qMSQuhNZ8+X6V-aGo}dv<;(gfBo=h"
    "yx8Y=!15GU)&bug@EyWJJ0LlM8Yif4f_f&XXM%brsAq!bCeY;sx}2bv30!Le)F)tf0?kdJxe1gufsf0-N>1Qp6L`=B5={W-1g0{9"
    "+9pu_R1UVnA13gJ3H-tD7^FR;WavV^4k#bH6c8rxyeVvH3ZtCLu~>Q73|yv>x&FO37}=UFd_y@C=xPF8O@&*y$aMVSk8nJ_DW4bp"
    "%V+AL+v#>+i}^~~bY{-0{{7+YuU4t6DYQL>wwLlhioz{aHi7$2po$5!Koge#B%Q*&rbg~~`{7T!^hh7qNqK!Je~-d|zcB`33J(C<"
    "K>BPzKLC6KNHl<+22jEPLJuI<01OPEjsdtBh?Rkr0TeTURSck=0Ze)T6%8Q!0D2k#umSWm0BUW}XruZzYHp*_wzQ$Bs*PIO;+iPi"
    "MzJ<HZG*qIe6sG($n3yxgVQ#cTy{VFxs@&yjJCmJyInr`agY7y@@KGa8|Ai*9@=wrjm^~<e%t7zy)@UAxvtGs`eRsl`=lhaKj%N{"
    "mxT6kmx?ljtUseqdoE7Ps2O%G;Q=zV388^D{G$Uul7Eouz=b-}|13%?fz@@y=io~nc^2h6aGnmFrz5Tk`8#q%0Cjf2U<cOIF-=s*"
    "G+iB-S%>W$X!+86g5V5vW@Q5~DVvpv{7)qa_^8YW0Ur<e!ieNbh3M6MsSV_P>D0lT4-NY;(3!O6;CcpSl;$}#L!u5$CXzq?l7IJ-"
    "gA(#5nrI+8Xz`YyzJw@!VI56vUxrD77Gi^)sSS-|2Ob`y5shU~2kDl$U7nRK+h3xM@oayY?=L_07lY6z1TCo??L-G{?=UqK<WHsH"
    "<4ZU|3`bwW0RnLpGg_I+e|^em5?&m@$^%$=AfHHr%&~NOuz^@+Qn360mOn$omO#h^f+X@kl<<Z?#;LNo9xf5UB?9=s)HHV;AfJHc"
    "0A3MDuP<tnX*t{?0Mqhq#sEw&<==auwE$&1K&b;kV#ytrdJ6V+_vCFDFbSdB5N6Sb$@F0neON>vO75Xx4+8d}yFMiEL-LONiyMIJ"
    "0JDzifjXvh?3fN!{>Z!o3+~DPzrhqbz;KD$mq4ilt#;6OckswkMo}=2CE#0vsU?_Nf~g*W?3F#>$h46?K+^*>Jpj^&Q7&OueHfhl"
    "xBSpF4nt`S{;*9LKANj(N<(=8C@=p2PEY<K8i017)s7i4^vv+3gND5aNqUf}2O)Y8q6c950JRTL2lu9SXsR!R0<m=f*^>bB_FzXn"
    "pwWZSJ=jMN_R)j(dQfH$4N4D2(u3N1Q2HgAg39|cNHJ5CC29y|Rst?USWyUVh0s<AmP47Jz#L-{dRI11Url|YFt|n!Ce(uxdqANF"
    "0eXP9hY>?hK!6GNAk^i)bG-8Rm(bvAK4da9lgXj^#M982c~7QWqAftzgX(+eF)z&#upT_VhnDTqRC(DmIWUeMjH4&UAr=b@=%KnE"
    "l+c6t!*lbz1ZD4XWvagXWUi(qzclXA2jYET-<Mmom3@GGX$Fu>QLqdUd!<+HC7u}erhl2*_8r`$Z%hDgw3P9h3{}h*TbIytABZo}"
    "4)l|<gz=`!t9=Egb(fFT_b*F&y|)+KGjoUH^7m9S+(%2Zl*u@Xb5JX5Hc(y+z4av!<-s;XAee|v0LBC?CQwKMBTr;_h6<)K9hPny"
    "Ubh#$yc#VpWf%olTFMAVIsoxzSuc>)9~ff{6O2J5M*Xq4zBHurN1g(Qw5IZQ6@pJ?B)Kl-F=L+Pyo?(sjzMP$i7q83<z>u`*aX%&"
    "DMwFZ`7{csPGmSHQpu1}4(h?`rclrnE{1`|#He!eQsOKFSl~B-*GvH21e{IKC{3gpfQ$9Nm(A0Dv^m=MMC&uToQWdLr+WXKjrMux"
    "`@8Y}?(_a`xW5ecm;GGlEZJXV4D%;?+F#7FLLY4RWjY1d?~751J;4n6(yx?;KQZm{;OpK;%@FKmf4Sc$UhnVro#|*#Zggh~N>3sE"
    "_<f1zm-2@R#zpxn=O*KFm^LowE8|Z2Ll<0<90%nuEPrqmDUFu3F9U#bur>U(AJCR&@89mDdp0ijUq&itPJetuyq}hFY23^4OgWMI"
    "<L?>w_g{(ffA25GBs*xV`e;1*Xgqpo`KHo<LVdlb5B&I&`L5F>-iyD-{`;W(l|ANn*!vA^Czte=j2!-a+yi)B3UytM6R*psuP;CR"
    "qh)L}gh_;DKQ-B_aQwO_VdkNI>BdAoWzDx`;j7ZvM!}wey}GYUEU!x(zn4#ZFUqR3eXeO__v*hE>-i6{jQ<dn{+#}8mRN2+{3kRM"
    "pMHG!&*u7H%=N#T>wh!X|8B1TX0HFkT>q!J{x5U=-{$&%%(Y}6Z9rdoUg_X4T<A*%-2Jmb;|yy5Y+UsWEyNj|`K$!*)C~2`N)UUd"
    "RX#(Pc!uumb8b?ggwJLj^bB3(8La#aR{jN+^u-kYV*0-?Q1%y?=~uMfU*Pgz<Y_dGU%|o`v~^$57Jb=%_{W9#=07e>%lie*!x!;p"
    "JaGdFZy@1~NQjIZh<Ov0N?nydv^6(qux`-c+@NQW^|Tup;f>^$kFCqu-1@4t?Y$9Q?ycf7FMp*)5BIJ%G?SA)Way(=>4ViiWaxvh"
    "zHD9+&;dms=G=!|zDzG=)Q1kx2kZXUObxc|Gi08_TVwTj7<VJn-ks0O--3~ZktHK5M%IknG4jaBhLI;melhaQ$O|JoMt(DrGLkWZ"
    "#``?R4I?ol2_s8JR*b9}xn<;zk$XlS8QCzhW#oyGUyM96^1{fDkyl1iMsh}k`30F@5Z(ouUy$bod0vp`1$jo~fssc>HjHc;d1B-z"
    "Bfl7VX5=>`uZ*OOWQ^pD2=fWyO~_$F3==Yzke`HXBrLw9>`ThNWQ9vsxTMHSvbrSBOX9pF^DDx#A{#5Ru_7BQvaw=?YqGJX{j8~i"
    "HThXn7i%)MCSz+7T~h^X(ppmmYa+iU^6M(~7e;oB{AMI&M3BFwIJYEmOA@!N@Rs%5vYtD_dq=tMDAyf%zGH=VtniLN-I3=zlDH$!"
    "ccgXC3h!CZJ&WH{_6I)mKnx#<;R7*zVDSgC@lY-P%t*>e&WKplBUSlGRX$SoN0N9XhL5c9k>Wg3oJT_UNOyQ7tqn<RSo4OcZYbb}"
    "*0Q0b8%nw%^$n5VP~;6o-VnMCW#3Q*8}hs%&l~c*A<rA~ydh8<y6~ndg&?-2I9rOdr4(CAv85DSVz?#qTe7+(t6OroB|lrzdZMI1"
    "N%SXa{UoiQr1g`C{Ul;PN%Uv6o-HHKjJz<iV<crnWdB9#&!qlLDV|yUnan@4_zO$D(6nBN*b5Edg%!R~iWf@pLg-%DG`&!+7s~ZQ"
    "xn3yO3mJQ%fG_0mg#x}%-7nPg3nhIa@;frWBhNeXyd&~E^1LI@JF>bXt2?r~Bda^Ix+AMQvbrOOJ94-qm^(7|n~eP?_1~=dH*5Y)"
    "k$+RJ-z@&h;;)qJl`42;g|9^Zl@-2HxhZ8&Ng|`9IqS(OML}8xIV_Ag{?q^a>tkI0{w{yB@^@$M3p;aL{(h9dr$d>~<!@~sD*ivD"
    "TZBC"
)


def _load_catalog() -> frozenset[str]:
    payload = zlib.decompress(base64.b85decode(_COMPRESSED_FULLY_QUALIFIED))
    if hashlib.sha256(payload).hexdigest() != REACTION_EMOJI_CATALOG_SHA256:
        raise RuntimeError("Bundled Unicode emoji catalog failed its integrity check")
    catalog = frozenset(payload.decode("utf-8").split("\n"))
    if len(catalog) != REACTION_EMOJI_CATALOG_SIZE:
        raise RuntimeError("Bundled Unicode emoji catalog has an unexpected size")
    return catalog


REACTION_EMOJI_SEQUENCES = _load_catalog()


def is_valid_reaction_emoji(value: object) -> bool:
    """Return whether *value* is one bounded, fully-qualified RGI emoji.

    The exact Unicode 18.0 membership set handles pictographs, symbols,
    regional-indicator flags, keycaps, variation selectors, skin tones, ZWJ
    sequences, and standardized tag flags without platform-dependent Unicode
    tables or third-party packages.
    """

    if not isinstance(value, str) or not value:
        return False
    if len(value) > MAX_REACTION_EMOJI_CODEPOINTS:
        return False
    try:
        if len(value.encode("utf-8", errors="strict")) > MAX_REACTION_EMOJI_UTF8_BYTES:
            return False
    except UnicodeEncodeError:
        return False
    return value in REACTION_EMOJI_SEQUENCES
