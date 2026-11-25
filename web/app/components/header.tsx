import Link from "next/link";

export default function Header() {
    return (
        <header>
            <nav>
                <Link href="/">Главная</Link>
                <Link href="/">Все брони</Link>
                <Link href="/">Забронировать</Link>
                <Link href="/">Каталог</Link>
                <Link href="/">Ассистент</Link>
            </nav>
        </header>
    );
}